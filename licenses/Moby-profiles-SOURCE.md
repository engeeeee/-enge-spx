# Moby seccomp policy

Browser policy derived from https://github.com/moby/profiles/blob/4b8214fc4971e06172938a1f1554ccff6647ee80/seccomp/default.json (Apache-2.0).

The ENGE SPX delta allows only clone user/PID/network namespace bit combinations and unshare(CLONE_NEWUSER). It does not allow clone3, arbitrary setns, mount, bpf or unrestricted seccomp. Capability-gated upstream rules remain conditional; the browser drops all capabilities. The pinned default policy preserves its address-family exclusions, including AF_ALG.
