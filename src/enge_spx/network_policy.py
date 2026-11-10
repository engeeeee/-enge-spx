"""Versioned, stopped-only bridge upgrades without replacing project layers."""
from copy import deepcopy
import ipaddress

from .state import SPXError

MODE = "com.docker.network.bridge.gateway_mode_ipv4"
JOURNAL = "network-upgrade.json"


def validate(engine, obj, internal):
    engine.owned(obj)
    if obj.get("Internal") is not internal or obj.get("Driver") != "bridge" or obj.get("EnableIPv6"):
        raise SPXError("容器网络的隔离配置不一致。")
    if internal and (obj.get("Options") or {}).get(MODE) != "isolated":
        raise SPXError("内部网络尚未升级为 isolated 模式，请重新检查连接；不会启用旧网络兜底。")


def _create(engine, name, original=None, isolated=True):
    args = ["network", "create", "--internal"]
    labels = (original or {}).get("Labels") or {engine.owner: engine.store.instance}
    for key, value in sorted(labels.items()):
        args += ["--label", key + "=" + value]
    if original:
        for config in original["IPAM"]["Config"]:
            for key, flag in (("Subnet", "--subnet"), ("Gateway", "--gateway"), ("IPRange", "--ip-range")):
                if config.get(key):
                    args += [flag, config[key]]
            for key, value in sorted((config.get("AuxiliaryAddresses") or {}).items()):
                args += ["--aux-address", key + "=" + value]
    options = dict((original or {}).get("Options") or {})
    if isolated:
        options[MODE] = "isolated"
    for key, value in sorted(options.items()):
        args += ["--opt", key + "=" + value]
    engine.docker.run(*args, name)


def _owned_endpoints(engine, obj):
    for identifier in obj.get("Containers") or {}:
        engine.owned(engine.docker.inspect("container", identifier))
    result = []
    for identifier in engine.managed():
        container = engine.owned(engine.docker.inspect("container", identifier))
        endpoint = (container.get("NetworkSettings", {}).get("Networks") or {}).get(engine.internal)
        if endpoint is not None:
            address = endpoint.get("IPAddress") or (endpoint.get("IPAMConfig") or {}).get("IPv4Address")
            if not address:
                raise SPXError("旧网络缺少可恢复的容器地址，已保留容器和数据，请先停止环境后重试。")
            result.append({"id": container["Id"], "ipv4": str(ipaddress.IPv4Address(address))})
    return result


def _stopped(engine, endpoints):
    identifiers = {endpoint["id"] for endpoint in endpoints} | set(engine.managed())
    for identifier in identifiers:
        obj = engine.owned(engine.docker.inspect("container", identifier))
        if obj["State"]["Running"]:
            raise SPXError("网络升级要求所有关联容器先停止，未修改运行中的容器。")


def _connect(engine, endpoints):
    for endpoint in endpoints:
        obj = engine.owned(engine.docker.inspect("container", endpoint["id"]))
        networks = obj.get("NetworkSettings", {}).get("Networks") or {}
        if engine.internal not in networks:
            engine.docker.run("network", "connect", "--ip", endpoint["ipv4"], engine.internal, endpoint["id"])
            obj = engine.owned(engine.docker.inspect("container", endpoint["id"]))
            networks = obj.get("NetworkSettings", {}).get("Networks") or {}
        current = networks.get(engine.internal) or {}
        address = current.get("IPAddress") or (current.get("IPAMConfig") or {}).get("IPv4Address")
        if address != endpoint["ipv4"]:
            raise SPXError("恢复的容器地址与迁移记录不一致，环境保持停止。")


def _replace(engine, original, endpoints, isolated):
    _stopped(engine, endpoints)
    obj = engine.docker.inspect("network", engine.internal)
    if obj:
        engine.owned(obj)
        # Never detach a foreign endpoint, even during error recovery.
        for identifier in obj.get("Containers") or {}:
            engine.owned(engine.docker.inspect("container", identifier))
        for endpoint in endpoints:
            container = engine.owned(engine.docker.inspect("container", endpoint["id"]))
            if engine.internal in (container.get("NetworkSettings", {}).get("Networks") or {}):
                engine.docker.run("network", "disconnect", engine.internal, endpoint["id"])
        engine.docker.run("network", "rm", engine.internal)
    _create(engine, engine.internal, original, isolated)
    _connect(engine, endpoints)


def upgrade(engine, obj):
    saved = engine.store.read(JOURNAL, {})
    recovering = saved.get("phase") in ("upgrading", "rollback-failed")
    if recovering:
        if saved.get("schema") != 1 or saved.get("instance") != engine.store.instance or saved.get("network") != engine.internal:
            raise SPXError("网络迁移记录不匹配，已保留原资源。")
        original, endpoints = saved["original"], saved["endpoints"]
        engine.owned(original)
    else:
        if not obj:
            _create(engine, engine.internal)
            return
        engine.owned(obj)
        if obj.get("Internal") is not True or obj.get("Driver") != "bridge" or obj.get("EnableIPv6"):
            raise SPXError("旧内部网络不符合升级条件，未修改原资源。")
        if (obj.get("Options") or {}).get(MODE) == "isolated":
            return
        endpoints = _owned_endpoints(engine, obj)
        original = {key: deepcopy(obj.get(key)) for key in ("Labels", "Options", "IPAM")}
        original.update(Internal=True, Driver="bridge", EnableIPv6=False)
        configs = (original.get("IPAM") or {}).get("Config") or []
        if len(configs) != 1 or ipaddress.ip_network(configs[0]["Subnet"]).version != 4:
            raise SPXError("旧内部网络的地址分配不支持自动升级，未修改原资源。")
    # Stop before disconnecting namespaces; the gateway lease is revoked first.
    # This also protects a resumed, interrupted migration from stale processes.
    engine._stop("正在升级内部网络隔离策略，项目和账号数据会保留。")
    _stopped(engine, endpoints)
    record = {"schema": 1, "instance": engine.store.instance, "network": engine.internal, "phase": "upgrading", "original": original, "endpoints": endpoints}
    engine.store.write(JOURNAL, record)
    try:
        current = engine.docker.inspect("network", engine.internal)
        if current and (current.get("Options") or {}).get(MODE) == "isolated":
            validate(engine, current, True)
            _connect(engine, endpoints)
        else:
            _replace(engine, original, endpoints, True)
        validate(engine, engine.docker.inspect("network", engine.internal), True)
        _stopped(engine, endpoints)
        engine.store.write(JOURNAL, {**record, "phase": "complete", "policy": 1})
    except Exception as error:
        try:
            _replace(engine, original, endpoints, False)
            engine.store.write(JOURNAL, {**record, "phase": "rolled-back"})
        except Exception:
            engine.store.write(JOURNAL, {**record, "phase": "rollback-failed"})
        raise SPXError("内部网络升级未完成，环境保持停止，容器和数据已保留。请重试准备；不会启动旧网络作为回退。") from error


def ensure(engine):
    external = engine.docker.inspect("network", engine.external)
    if not external:
        engine.docker.run("network", "create", "--label", engine.owner + "=" + engine.store.instance, engine.external)
        external = engine.docker.inspect("network", engine.external)
    validate(engine, external, False)
    upgrade(engine, engine.docker.inspect("network", engine.internal))
    internal = engine.docker.inspect("network", engine.internal)
    validate(engine, internal, True)
    subnet = ipaddress.ip_network(internal["IPAM"]["Config"][0]["Subnet"])
    return str(subnet[2]), str(subnet[3])
