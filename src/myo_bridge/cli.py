"""Command line: scan, dump (M1); run / monitor / sleep added in later milestones."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from typing import Annotated, Optional

import typer

from myo_bridge import __version__
from myo_bridge.config import load_config
from myo_bridge.myo import protocol as P
from myo_bridge.myo.device import DeviceConfig, MyoDevice
from myo_bridge.transport.base import TransportError

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="OSA MYO Controller: Myo armband BLE driver, monitor and OSC bridge.")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if not verbose:
        logging.getLogger("bleak").setLevel(logging.WARNING)
        # dump/run print their own event lines; keep the device logger quiet
        logging.getLogger("myo_bridge.myo.device").setLevel(logging.WARNING)


def _backend(transport: str | None, port: str | None):
    """(config, transport factory, scanner): --transport / --port, else the saved settings."""
    from myo_bridge.engine import make_backend
    cfg = load_config()
    if transport:
        cfg.transport = transport
    if port is not None:
        cfg.dongle_port = port
    try:
        factory, scanner = make_backend(cfg.transport, cfg)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from None
    return cfg, factory, scanner


TRANSPORT_HELP = "bleak (built-in Bluetooth) | bled112 (USB dongle) | mock; default: saved settings"
PORT_HELP = "BLED112 serial port, e.g. /dev/cu.usbmodem11 (default: saved settings, else auto-detect)"


@app.callback(invoke_without_command=True)
def _main(version: Annotated[bool, typer.Option("--version", is_eager=True)] = False) -> None:
    if version:
        typer.echo(f"OSA MYO Controller {__version__}")
        raise typer.Exit()


@app.command()
def scan(
    timeout: Annotated[float, typer.Option(help="seconds to scan")] = 6.0,
    all_devices: Annotated[bool, typer.Option("--all", help="list every BLE device")] = False,
    transport: Annotated[Optional[str], typer.Option(help=TRANSPORT_HELP)] = None,
    port: Annotated[Optional[str], typer.Option(help=PORT_HELP)] = None,
    verbose: Annotated[bool, typer.Option("-v")] = False,
) -> None:
    """Scan for Myo armbands and list them with RSSI."""
    _setup_logging(verbose)
    cfg, _factory, scanner = _backend(transport, port)

    async def _run():
        typer.echo(f"scanning for {timeout:g}s with {cfg.transport} ...")
        try:
            results = await scanner.scan(timeout=timeout, myo_only=not all_devices)
        except TransportError as e:
            typer.echo(f"scan failed: {e}")
            raise typer.Exit(1)
        if not results:
            hint = ("is the dongle plugged in (osa-myo ports)?" if cfg.transport == "bled112"
                    else "make sure Bluetooth permission is granted to the terminal.")
            typer.echo("no Myo found. Is it awake (blue logo pulsing)? Charge it via USB "
                       f"or tap it; {hint}")
            return
        typer.echo(f"{'name':20} {'rssi':>5}  {'address / uuid':38} myo")
        for r in results:
            typer.echo(f"{r.display_name:20} {str(r.rssi):>5}  {r.address:38} {'yes' if r.is_myo else ''}")

    asyncio.run(_run())


@app.command()
def dump(
    device: Annotated[Optional[str], typer.Option("--device", "-d",
                      help="Myo name or address/UUID; default: first Myo found")] = None,
    emg: Annotated[int, typer.Option(help="EMG mode 0 off, 1 smooth, 2 filtered, 3 raw")] = 3,
    imu: Annotated[int, typer.Option(help="IMU mode 0 off, 1 data, 2 events, 3 all, 4 raw")] = 3,
    classifier: Annotated[int, typer.Option(help="classifier 0 off, 1 on")] = 1,
    duration: Annotated[float, typer.Option(help="seconds to stream (0 = until Ctrl-C)")] = 0,
    show_emg: Annotated[bool, typer.Option(help="print every EMG sample")] = False,
    show_imu: Annotated[bool, typer.Option(help="print every IMU packet")] = False,
    hex_dump: Annotated[bool, typer.Option("--hex", help="print raw hex of event packets")] = True,
    no_sleep_restore: Annotated[bool, typer.Option(help="leave the Myo in never-sleep")] = False,
    transport: Annotated[Optional[str], typer.Option(help=TRANSPORT_HELP)] = None,
    port: Annotated[Optional[str], typer.Option(help=PORT_HELP)] = None,
    verbose: Annotated[bool, typer.Option("-v")] = False,
) -> None:
    """Connect to one Myo and print parsed packets, rates and drop counters (hardware test)."""
    _setup_logging(verbose)
    cfg, factory, scanner = _backend(transport, port)

    async def _run():
        typer.echo(f"looking for a Myo with {cfg.transport} ...")
        try:
            found = await scanner.find(device, timeout=cfg.scan_timeout_s * 2)
        except TransportError as e:
            typer.echo(f"scan failed: {e}")
            raise typer.Exit(1)
        if found is None:
            typer.echo("no Myo found")
            raise typer.Exit(1)
        typer.echo(f"found {found.display_name} @ {found.address}")
        dev = MyoDevice(factory(), device_id=1,
                        config=DeviceConfig(emg_mode=P.EmgMode(emg), imu_mode=P.ImuMode(imu),
                                            classifier_mode=P.ClassifierMode(classifier)),
                        selector=found.address)
        t0 = time.monotonic()
        last_imu_print = [0.0]

        def pr(kind: str, msg: str) -> None:
            typer.echo(f"{time.monotonic() - t0:8.3f} {kind:6} {msg}")

        dev.on_state.connect(lambda d, s: pr("state", s.value))
        dev.on_log.connect(lambda d, m: pr("log", m))
        dev.on_battery.connect(lambda d, b: pr("batt", f"{b}%"))
        dev.on_rssi.connect(lambda d, r: pr("rssi", f"{r} dBm"))

        @dev.on_classifier.connect
        def _cls(d, ev: P.ClassifierEvent, t):
            extra = ""
            if ev.type is P.ClassifierEventType.ARM_SYNCED:
                extra = f" arm={ev.arm.label} xdir={ev.x_direction.label}"
            elif ev.type is P.ClassifierEventType.POSE:
                extra = f" pose={ev.pose.label}"
            elif ev.type is P.ClassifierEventType.SYNC_FAILED:
                extra = f" result={ev.sync_result.name.lower()}"
            raw = f" raw={ev.raw.hex(' ')} ({len(ev.raw)} B)" if hex_dump else ""
            pr("class", f"{ev.label}{extra}{raw}")

        dev.on_motion.connect(lambda d, ev, t: pr("motion", f"{ev}"))

        @dev.on_imu.connect
        def _imu(d, pkt: P.ImuPacket, t):
            if show_imu or t - last_imu_print[0] > 1.0:
                last_imu_print[0] = t
                w, x, y, z = pkt.quat_f
                norm = (w * w + x * x + y * y + z * z) ** 0.5
                pr("imu", f"quat w={w:+.3f} x={x:+.3f} y={y:+.3f} z={z:+.3f} |q|={norm:.3f}  "
                          f"acc={tuple(round(v, 2) for v in pkt.accel_g)} g  "
                          f"gyro={tuple(round(v, 1) for v in pkt.gyro_dps)} dps")

        if show_emg:
            dev.on_emg.connect(lambda d, s, t: pr("emg", " ".join(f"{v:4d}" for v in s)))

        dev.on_fv.connect(lambda d, p, t: pr("fv", f"{p.values} mask={p.mask}") if show_emg else None)

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass

        try:
            await dev.connect(timeout=25)
        except TransportError as e:
            typer.echo(f"connect failed: {e}")
            raise typer.Exit(1)

        async def status_loop():
            while not stop.is_set():
                await asyncio.sleep(2.0)
                st = dev.stats
                emg = dev.last_emg or ()
                pr("stats", f"emg {st.emg_rate_hz:5.1f} sps (per char {st.emg_per_char}) "
                            f"dropped~{st.emg_dropped}  imu {st.imu_rate_hz:4.1f} Hz  "
                            f"fv={st.fv_packets} cls={st.classifier_events} "
                            f"sync={dev.synced} lock={dev.locked} pose={dev.pose.label} "
                            f"last emg={list(emg)}")

        task = asyncio.create_task(status_loop())
        try:
            if duration > 0:
                await asyncio.wait_for(stop.wait(), timeout=duration)
            else:
                await stop.wait()
        except asyncio.TimeoutError:
            pass
        task.cancel()
        typer.echo("shutting down (restoring sleep mode) ...")
        await dev.disconnect(restore_sleep=not no_sleep_restore)

    asyncio.run(_run())


@app.command()
def ports() -> None:
    """List serial ports (to find the BLED112 dongle's port)."""
    from myo_bridge.transport.bled112_transport import list_serial_ports
    try:
        found = list_serial_ports()
    except TransportError as e:
        typer.echo(str(e))
        raise typer.Exit(1)
    if not found:
        typer.echo("no serial ports: plug the BLED112 dongle in")
        return
    for dev, desc, likely in found:
        typer.echo(f"{dev:36} {desc:28} {'<- BLED112' if likely else ''}")


@app.command()
def monitor(
    mock: Annotated[bool, typer.Option("--mock", help="use simulated armbands")] = False,
    devices: Annotated[Optional[int], typer.Option("-n", help="number of armbands")] = None,
    config_path: Annotated[Optional[str], typer.Option("--config")] = None,
    verbose: Annotated[bool, typer.Option("-v")] = False,
) -> None:
    """Open the monitor GUI without auto-connecting (use SCAN / CONNECT in the window)."""
    _setup_logging(verbose)
    from myo_bridge.config import DeviceEntry
    cfg = load_config(config_path)
    if mock:
        cfg.transport = "mock"
    if devices:
        cur = list(cfg.devices)
        while len(cur) < devices:
            cur.append(DeviceEntry())
        cfg.devices = cur[:devices]
    from myo_bridge.gui.app import run_gui
    raise typer.Exit(run_gui(cfg, autoconnect=False))


@app.command()
def run(
    no_gui: Annotated[bool, typer.Option("--no-gui", help="headless: stream OSC only")] = False,
    mock: Annotated[bool, typer.Option("--mock", help="use simulated armbands")] = False,
    transport: Annotated[Optional[str], typer.Option(help=TRANSPORT_HELP)] = None,
    port: Annotated[Optional[str], typer.Option(help=PORT_HELP)] = None,
    osc_host: Annotated[Optional[str], typer.Option()] = None,
    osc_port: Annotated[Optional[int], typer.Option()] = None,
    osc_in_port: Annotated[Optional[int], typer.Option()] = None,
    preset: Annotated[Optional[str], typer.Option(help="OSC namespace: default | myomapper")] = None,
    mode: Annotated[Optional[str], typer.Option(help="vector | axis")] = None,
    device: Annotated[Optional[list[str]], typer.Option("--device", "-d",
                      help="Myo name/UUID per slot (repeat for several); default: config")] = None,
    devices: Annotated[Optional[int], typer.Option("-n", help="number of armbands (first found)")] = None,
    emg: Annotated[Optional[int], typer.Option(help="EMG mode for all slots")] = None,
    config_path: Annotated[Optional[str], typer.Option("--config")] = None,
    verbose: Annotated[bool, typer.Option("-v")] = False,
) -> None:
    """Connect the configured armbands and stream OSC (with the monitor GUI unless --no-gui)."""
    _setup_logging(verbose)
    from myo_bridge.config import DeviceEntry
    cfg = load_config(config_path)
    if mock:
        cfg.transport = "mock"
    if transport:
        cfg.transport = transport
    if port is not None:
        cfg.dongle_port = port
    if osc_host:
        cfg.osc.host = osc_host
    if osc_port:
        cfg.osc.port = osc_port
    if osc_in_port:
        cfg.osc_in.port = osc_in_port
    if preset:
        cfg.osc.preset = preset
    if mode:
        cfg.osc.mode = mode
    if device:
        cfg.devices = [DeviceEntry(selector=d) for d in device]
    if devices:
        cur = list(cfg.devices)
        while len(cur) < devices:
            cur.append(DeviceEntry())
        cfg.devices = cur[:devices]
    if emg is not None:
        for d in cfg.devices:
            d.emg_mode = emg

    if not no_gui:
        from myo_bridge.gui.app import run_gui
        raise typer.Exit(run_gui(cfg))

    from myo_bridge.engine import Bridge, make_backend

    async def _run():
        factory, scanner = make_backend(cfg.transport, cfg)
        bridge = Bridge(cfg, factory, scanner)
        bridge.on_log_listeners.append(
            lambda e: typer.echo(f"{e.t:12.3f} myo{e.device_id} {e.kind:16} {e.text}"))
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
        server = None
        if cfg.osc_in.enabled:
            from myo_bridge.osc.server import OscControlServer
            server = OscControlServer(bridge, cfg.osc_in.host, cfg.osc_in.port)
            await server.start()
        typer.echo(f"OSC -> {cfg.osc.host}:{cfg.osc.port} (preset={cfg.osc.preset}, mode={cfg.osc.mode}); "
                   f"control <- :{cfg.osc_in.port}; Ctrl-C to stop")

        async def stats_loop():
            while not stop.is_set():
                await asyncio.sleep(5.0)
                parts = []
                for s in bridge.slots:
                    st = s.device.stats
                    parts.append(f"myo{s.id} {s.device.state.value} emg {st.emg_rate_hz:.0f}sps "
                                 f"drop {st.emg_dropped} imu {st.imu_rate_hz:.0f}Hz "
                                 f"lat {s.processor.emg_latency_ms:.1f}ms")
                typer.echo(" | ".join(parts) + f" | osc dgrams {bridge.osc.sent_datagrams}")

        task = asyncio.create_task(stats_loop())
        try:
            await bridge.run(stop)
        finally:
            task.cancel()
            if server:
                await server.stop()

    asyncio.run(_run())


@app.command()
def credits() -> None:
    """Authors, contact and the open-source projects OSA MYO Controller is built on."""
    from myo_bridge.credits import credits_text

    typer.echo(credits_text())


@app.command()
def config_show() -> None:
    """Print the effective configuration as TOML."""
    from myo_bridge.config import config_to_toml
    cfg = load_config()
    typer.echo(f"# {cfg.path}")
    typer.echo(config_to_toml(cfg))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
