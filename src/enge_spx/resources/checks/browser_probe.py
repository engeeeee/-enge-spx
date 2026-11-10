"""Observe the real profile using a short-lived, unpublished loopback page.

No DevTools listener, profile/account file read, external STUN or fingerprint override.
The one-use browser authorization arrives on stdin and is never returned or logged.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import urllib.request


def collect(token):
    nonce = secrets.token_hex(24)
    complete, stopped = threading.Event(), threading.Event()
    result = {}
    udp_count = [0]
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.settimeout(.2)
    def udp_sink():
        while not stopped.is_set():
            try:
                udp.recvfrom(2048)
                udp_count[0] = min(65535, udp_count[0] + 1)
            except socket.timeout:
                continue
            except OSError:
                break
    sink = threading.Thread(target=udp_sink, daemon=True)
    sink.start()
    get_path, post_path = "/observe/" + nonce, "/evidence/" + nonce
    javascript = '''(async()=>{
const data={language:navigator.language,languages:Array.from(navigator.languages||[]).slice(0,8),timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,offset_minutes:-new Date().getTimezoneOffset(),webrtc:{available:typeof RTCPeerConnection==='function',offer_created:false,candidates:[]}};
let peer;
try{
 if(data.webrtc.available){
  peer=new RTCPeerConnection({iceServers:[{urls:'stun:127.0.0.1:STUN_PORT'}]});
  peer.createDataChannel('spx-local-observation');
  peer.onicecandidate=e=>{if(e.candidate&&data.webrtc.candidates.length<16){const c=e.candidate;data.webrtc.candidates.push({type:c.type,protocol:c.protocol,address:c.address});}};
  await peer.setLocalDescription(await peer.createOffer());data.webrtc.offer_created=true;
  await new Promise(resolve=>{if(peer.iceGatheringState==='complete')resolve();else{peer.onicegatheringstatechange=()=>{if(peer.iceGatheringState==='complete')resolve();};setTimeout(resolve,2000);}});
  data.webrtc.gathering_state=peer.iceGatheringState;
 }
}catch(error){data.webrtc.error_class=String(error.name).slice(0,40);}
finally{if(peer)peer.close();}
await fetch('POST_PATH',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
})();'''.replace("STUN_PORT", str(udp.getsockname()[1])).replace("POST_PATH", post_path)
    body = ("<!doctype html><meta charset='utf-8'><title>ENGE SPX Network Observation</title><p>Observing language, timezone and local WebRTC behavior. You may close this page after the app completes its report.</p><script nonce='" + nonce + "'>" + javascript + "</script>").encode()
    origin = ""
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(3)
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.path != get_path or self.headers.get("Host") != origin.removeprefix("http://"):
                self.send_error(404)
                return
            # Never inspect Cookie, Authorization, Storage or the profile files.
            result["accept_language"] = self.headers.get("Accept-Language", "")[:256]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'nonce-" + nonce + "'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            if self.path != post_path or self.headers.get("Origin") != origin or self.headers.get("Host") != origin.removeprefix("http://"):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    raise ValueError()
                value = json.loads(self.rfile.read(size))
                if not isinstance(value, dict):
                    raise ValueError()
                result["observation"] = value
                self.send_response(204)
                self.end_headers()
                complete.set()
            except (ValueError, OSError):
                self.send_error(400)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    origin = "http://127.0.0.1:" + str(server.server_port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request("http://127.0.0.1:6081/open", data=json.dumps({"url": origin + get_path}).encode(), headers={"Content-Type": "application/json", "X-SPX-Token": token})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=12) as response:
                if response.status != 204:
                    return {"schema": 1, "available": False, "reason": "browser_open_failed"}
        except TimeoutError:
            return {"schema": 1, "available": False, "reason": "browser_open_timeout"}
        except (OSError, ValueError):
            return {"schema": 1, "available": False, "reason": "browser_open_failed"}
        if not complete.wait(5):
            return {"schema": 1, "available": False, "reason": "page_not_observed"}
        result.update(schema=1, available=True, local_stun_datagrams=udp_count[0], context="container-loopback STUN sink only; no public STUN/TURN tested")
        try:
            policy = json.loads(Path("/etc/chromium/policies/managed/spx.json").read_text())
            result["webrtc_policy_file"] = "disable_non_proxied_udp" if policy.get("WebRtcIPHandling") == "disable_non_proxied_udp" else "other_or_missing"
        except (ValueError, OSError):
            result["webrtc_policy_file"] = "unavailable"
        return result
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        udp.close()
        sink.join(1)


if __name__ == "__main__":
    try:
        value = json.loads(sys.stdin.buffer.read(4097))
        token = value.get("token", "")
        if not isinstance(token, str) or re.fullmatch(r"[a-f0-9]{64}", token) is None:
            raise ValueError()
        print(json.dumps(collect(token)))
    except Exception:
        print(json.dumps({"schema": 1, "available": False, "reason": "browser_observation_unavailable"}))
