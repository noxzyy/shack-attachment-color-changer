import argparse
import concurrent.futures
import getpass
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath


PACKAGES = ('com.vankrupt.pavlov',)
ENTRY = b'Pavlov/Content/Paks/pakchunk100-Android_ASTC.pak'
DEVICE = ''
ADB = ''

def require(value, message='something failed'):  # stop if the check fails
    if not value:
        raise RuntimeError(message)

def plain(value):
    value = re.sub(r'(?i)skin[ -]lab', 'skinnard', str(value)).lower()
    return ' '.join(re.sub(r'[^a-z0-9\s]', ' ', value).split())

def title(value):
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(plain('pavlov mods ' + value))
        except Exception:
            pass

def download_adb(): #aadbadbadbadbadbadbadbadbadbdbdbddabadbadadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbaadbadebadbadadaddaadbadbdabadbadbdabdabdabadbdabdabdadabadbdabadadbadbadbadbadbdabadbadbadbadbadbadbadbdabdabadbadbadbadbad
    platform = 'windows' if sys.platform == 'win32' else 'darwin' if sys.platform == 'darwin' else 'linux'
    executable = 'adb.exe' if platform == 'windows' else 'adb'
    directory = Path(__file__).resolve().parent / 'req' / 'tools'
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='adb-', dir=directory) as temporary:
        stage = Path(temporary).resolve()
        archive = stage / 'platform-tools.zip'
        url = 'https://dl.google.com/android/repository/platform-tools-latest-' + platform + '.zip'
        with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        with zipfile.ZipFile(archive) as packed:
            require(packed.testzip() is None)
            for item in packed.infolist():
                require('\\' not in item.filename)
                target = (stage / item.filename).resolve()
                require(target.is_relative_to(stage / 'platform-tools'))
                require((item.external_attr >> 16) & 0o170000 != 0o120000)
            require('platform-tools/' + executable in packed.namelist())
            if platform == 'windows':
                require(all('platform-tools/' + name in packed.namelist() for name in ('AdbWinApi.dll', 'AdbWinUsbApi.dll')))
            packed.extractall(stage)
        shutil.copytree(stage / 'platform-tools', directory / 'platform-tools', dirs_exist_ok=True)
    path = directory / 'platform-tools' / executable
    require(path.is_file())
    if platform != 'windows':
        path.chmod(path.stat().st_mode | 0o111)
    return str(path)

def adb_path():
    executable = 'adb.exe' if os.name == 'nt' else 'adb'
    path = Path(__file__).resolve().parent / 'req' / 'tools' / 'platform-tools' / executable
    if path.is_file():
        return str(path)
    return download_adb()

def host(*args, timeout=15, check=True, data=None):
    result = subprocess.run([ADB, *map(str, args)], input=data, capture_output=True, timeout=timeout)
    if check:
        detail = (result.stderr or result.stdout).decode(errors='replace').strip()
        require(result.returncode == 0, 'adb failed ' + (detail[-1800:] or 'exit code ' + str(result.returncode)))
    return result.stdout

def transports():
    result = {}
    for line in host('devices', '-l').decode(errors='replace').splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] in ('device', 'offline', 'unauthorized', 'recovery', 'sideload', 'rescue', 'bootloader', 'no'):
            result[fields[0]] = fields[1]
    return result

def identify(serial):
    def query(*args):
        return host('-s', serial, 'shell', *args, timeout=10).decode(errors='replace').strip()
    try:
        if not query('pm', 'path', PACKAGES[0]).startswith('package:'):
            return None
        identity = query('getprop', 'ro.serialno') or query('getprop', 'ro.boot.serialno')
        if not identity:
            identity = query('settings', 'get', 'secure', 'android_id')
        return (identity if identity and identity != 'null' else serial, serial)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return None

def headsets():
    devices = sorted(serial for serial, state in transports().items() if state == 'device' and ':' not in serial)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        identified = list(pool.map(identify, devices))
    result = {}
    for item in identified:
        if item:
            result.setdefault(item[0], item[1])
    return list(result.values())

def discover(wait=60):
    host('start-server')
    deadline = time.monotonic() + wait
    while True:
        current = {serial: state for serial, state in transports().items() if ':' not in serial}
        found = headsets()
        if found:
            return found[0]
        if time.monotonic() >= deadline:
            raise RuntimeError('allow the usb debugging popup on the headset')
        title('allow the usb debugging popup' if 'unauthorized' in current.values() else 'waiting on the headset')
        time.sleep(min(1, max(0, deadline - time.monotonic())))

def adb(*args, check=True):
    result = subprocess.run([ADB, '-s', DEVICE, *map(str, args)], capture_output=True, timeout=180)
    if check:
        require(result.returncode == 0)
    return result.stdout


DEVICE = ''
ENTRY = b'Pavlov/Content/Paks/pakchunk100-Android_ASTC.pak'

def read(path, offset, length):  # pull bytes from the obb
    require(offset >= 0 and 0 < length <= 8000000)
    remainder = offset % 4096
    result = adb('exec-out', 'dd', 'if=' + path, 'bs=4096', 'skip=' + str(offset // 4096), 'count=' + str((remainder + length + 4095) // 4096))
    result = result[remainder:remainder + length]
    require(len(result) == length)
    return result

def inspect(package):
    path = '/sdcard/Android/obb/' + package + '/main.2397.' + package + '.obb'
    require(re.search(rb'\bversionCode=2397\b', adb('shell', 'dumpsys', 'package', package)), 'this tool needs pavlov build 2397')
    size = int(adb('shell', 'stat', '-c', '%s', path).strip())
    start = max(0, size - 65557)
    tail = read(path, start, size - start)
    end = tail.rfind(b'PK\x05\x06')
    require(end >= 0 and end + 22 <= len(tail))
    require(end + 22 + struct.unpack_from('<H', tail, end + 20)[0] == len(tail))
    cdsize, cdoff = struct.unpack_from('<II', tail, end + 12)
    require(0 < cdsize <= 8000000 and cdoff + cdsize == start + end)
    cd = read(path, cdoff, cdsize)
    position = 0
    found = []
    while position < len(cd):
        require(cd[position:position + 4] == b'PK\x01\x02')
        n, e, c = struct.unpack_from('<HHH', cd, position + 28)
        require(position + 46 + n + e + c <= len(cd))
        if cd[position + 46:position + 46 + n] == ENTRY:
            found.append(position)
        position += 46 + n + e + c
    require(position == len(cd) and len(found) == 1)
    position = found[0]
    crc, compressed, length = struct.unpack_from('<III', cd, position + 16)
    require(compressed == length and 0 < length <= 8000000, 'this game file layout is not supported')
    local = struct.unpack_from('<I', cd, position + 42)[0]
    header = read(path, local, 30)
    require(header[:4] == b'PK\x03\x04')
    flags, method = struct.unpack_from('<HH', header, 6)
    require(method == 0 and not flags & 1)
    require((flags, method) == struct.unpack_from('<HH', cd, position + 8))
    n, e = struct.unpack_from('<HH', header, 26)
    require(read(path, local + 30, n) == ENTRY)
    base = local + 30 + n + e
    require(base + length <= cdoff)
    previous = read(path, base, length)
    require(zlib.crc32(previous) == crc)
    crc_offsets = [cdoff + position + 16]
    if flags & 8:
        descriptor = read(path, base + length, 16)
        shift = 4 if descriptor[:4] == b'PK\x07\x08' else 0
        require(struct.unpack_from('<III', descriptor, shift) == (crc, length, length))
        crc_offsets.append(base + length + shift)
    else:
        require(struct.unpack_from('<III', header, 14) == (crc, length, length))
        crc_offsets.append(local + 14)
    return dict(package=package, path=path, size=size, base=base, previous=previous, crc_offsets=crc_offsets)

def prepare(plan, payload, directory):
    spans = [(plan['base'], payload)]
    spans.extend((offset, struct.pack('<I', zlib.crc32(payload))) for offset in plan['crc_offsets'])
    ranges = []
    for offset, data in sorted(spans):
        start = offset // 4096 * 4096
        end = min(plan['size'], (offset + len(data) + 4095) // 4096 * 4096)
        if ranges and start <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], end)
        else:
            ranges.append([start, end])
    runs = []
    for index, (start, end) in enumerate(ranges):
        previous = read(plan['path'], start, end - start)
        modified = bytearray(previous)
        for offset, data in spans:
            left, right = max(start, offset), min(end, offset + len(data))
            if left < right:
                modified[left-start:right-start] = data[left-offset:right-offset]
        original_file = directory / ('original-' + str(index) + '.bin')
        modified_file = directory / ('patch-' + str(index) + '.bin')
        original_file.write_bytes(previous)
        modified_file.write_bytes(modified)
        runs.append(dict(offset=start, old=previous, new=bytes(modified), original_file=original_file, modified_file=modified_file))
    plan['runs'] = runs
    plan['record'] = directory / 'backup.json'
    plan['record'].write_text(json.dumps(dict(package=plan['package'], device=DEVICE, path=plan['path'], size=plan['size'], status='prepared', spans=[dict(offset=run['offset'], length=len(run['old']), original=run['original_file'].name, patch=run['modified_file'].name, original_sha256=hashlib.sha256(run['old']).hexdigest(), patch_sha256=hashlib.sha256(run['new']).hexdigest()) for run in runs]), indent=2), encoding='utf-8')

def status(plan, value):
    record = json.loads(plan['record'].read_text(encoding='utf-8'))
    record['status'] = value
    plan['record'].write_text(json.dumps(record, indent=2), encoding='utf-8')

def write(plan, restore=False):  # write the pak bytes back
    for run in plan['runs']:
        data = run['old'] if restore else run['new']
        local = run['original_file'] if restore else run['modified_file']
        require(local.read_bytes() == data)
        remote = '/data/local/tmp/noxzy-mods-' + uuid.uuid4().hex + '.bin'
        try:
            adb('push', local, remote)
            block = 4096 if run['offset'] % 4096 == len(data) % 4096 == 0 else 1
            adb('shell', 'dd', 'if=' + remote, 'of=' + plan['path'], 'bs=' + str(block), 'seek=' + str(run['offset'] // block), 'count=' + str(len(data) // block), 'conv=notrunc')
            require(read(plan['path'], run['offset'], len(data)) == data)
        finally:
            adb('shell', 'rm', '-f', remote, check=False)
    adb('shell', 'sync')
    require(int(adb('shell', 'stat', '-c', '%s', plan['path']).strip()) == plan['size'])



root = Path(__file__).resolve().parent

# sight color slots
slots = {
    "Pavlov/Content/Attachments/Laser_Base.uexp": 0xbc6,
    "Pavlov/Content/Attachments/Scope/Lenses/M_SightLense_Holo.uexp": 0x13c,
    "Pavlov/Content/Attachments/Scope/Lenses/M_SightLense_RedDot.uexp": 0x183,
    "Pavlov/Content/Attachments/Scope/Lenses/M_SightLense_RedDot_ForCantedSights.uexp": 0x189,
}

files = (
    "Pavlov/Content/Attachments/Laser_Base.uasset",
    "Pavlov/Content/Attachments/Laser_Base.uexp",
    "Pavlov/Content/Attachments/Scope/Lenses/M_SightLense_Holo.uasset",
    "Pavlov/Content/Attachments/Scope/Lenses/M_SightLense_Holo.uexp",
    "Pavlov/Content/Attachments/Scope/Lenses/M_SightLense_RedDot.uasset",
    "Pavlov/Content/Attachments/Scope/Lenses/M_SightLense_RedDot.uexp",
    "Pavlov/Content/Attachments/Scope/Lenses/M_SightLense_RedDot_ForCantedSights.uasset",
    "Pavlov/Content/Attachments/Scope/Lenses/M_SightLense_RedDot_ForCantedSights.uexp",
)


class parser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        if message:
            super()._print_message(plain(message) + "\n", file)


def run(*arguments):
    result = subprocess.run(list(map(str, arguments)), capture_output=True, timeout=180)
    require(result.returncode == 0, "game files could not be prepared " + (result.stderr or result.stdout).decode(errors="replace")[-1600:])
    return result.stdout.decode(errors="replace")


def srgb_to_linear(channel):
    # srgb byte to linear float
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def color_bytes(text):
    raw = text.strip().lower().removeprefix("#")
    require(len(raw) in (6, 8) and all(c in "0123456789abcdef" for c in raw), "give a hex")
    channels = [int(raw[i:i + 2], 16) / 255 for i in range(0, len(raw), 2)]
    if len(channels) == 3:
        channels.append(1)
    linear = [srgb_to_linear(channels[0]), srgb_to_linear(channels[1]), srgb_to_linear(channels[2]), channels[3]]
    return struct.pack("<4f", *linear)


def paint(path, color):
    if path.startswith("Pavlov/Content/Attachments/Laser_Base"):
        blob = bytearray((root / "req" / "laser" / path).read_bytes())
    else:
        blob = bytearray((root / "req" / "stock" / path).read_bytes())
    off = slots.get(path)
    if color is not None and off is not None:
        blob[off:off + 16] = color  # attachment color
    return bytes(blob)


def build(previous, action, color, temporary):
    repak = root / "req/tools/repak/repak.exe"
    require(repak.is_file(), "missing repak")
    source = temporary / "current.bin"
    source.write_bytes(previous)
    info = run(repak, "info", source).replace("\r\n", "\n")
    mount = next((line.removeprefix("mount point: ") for line in info.splitlines() if line.startswith("mount point: ")), "")
    require(mount.startswith("../../../") and ".." not in PurePosixPath(mount[9:]).parts and "version: V11\n" in info, "this game file format is not supported")
    listed = run(repak, "list", source).splitlines()
    for name in listed:
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name, "game archive contains an invalid file path")
    stage = temporary / "stage"
    run(repak, "unpack", source, "-o", stage)
    before = {file.relative_to(stage).as_posix(): file.read_bytes() for file in stage.rglob("*") if file.is_file()}
    expected = dict(before)
    for path in files:
        data = paint(path, color if action == "install" else None)
        if action == "remove":
            data = (root / "req" / "stock" / path).read_bytes()
        target = stage / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        expected[path] = data
    if before == expected:
        return previous
    packed = temporary / "patched.pak"
    run(repak, "pack", "--version", "V11", "--compression", "Zlib", stage, packed)
    payload = packed.read_bytes()
    footer = payload.rfind(b"\xe1\x12\x6f\x5a") - 17
    require(footer > 0, "game files could not be packed")
    require(len(payload) <= len(previous), "these mods do not fit this game file")
    payload = payload[:footer] + b"\0" * (len(previous) - len(payload)) + payload[footer:]
    packed.write_bytes(payload)
    verified = temporary / "verified"
    run(repak, "unpack", packed, "-o", verified)
    actual = {file.relative_to(verified).as_posix(): file.read_bytes() for file in verified.rglob("*") if file.is_file()}
    require(actual == expected, "prepared game files failed verification")
    return payload


def commit(plans):
    running = [plan["package"] for plan in plans if adb("shell", "pidof", plan["package"], check=False).strip()]
    touched = []
    try:
        for plan in plans:
            adb("shell", "am", "force-stop", plan["package"])
            require(not adb("shell", "pidof", plan["package"], check=False).strip(), "close pavlov and try again")
        for plan in plans:
            for row in plan["runs"]:
                require(read(plan["path"], row["offset"], len(row["old"])) == row["old"], "game files changed during setup try again")
        for plan in plans:
            touched.append(plan)
            status(plan, "writing")
            write(plan)
            require(inspect(plan["package"])["previous"] == plan["payload"], "the game file write failed verification")
            status(plan, "complete")
    except BaseException:
        restored = True
        for plan in reversed(touched):
            try:
                write(plan, restore=True)
                status(plan, "restored")
            except BaseException:
                restored = False
                status(plan, "restore-required")
        if not restored:
            raise RuntimeError("the connection failed during restore keep the backup folder and reconnect the headset")
        raise
    finally:
        for package in running:
            adb("shell", "am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.INFO", "-n", package + "/com.epicgames.unreal.GameActivity", check=False)


def main():
    global ADB, DEVICE
    print('1 change color')
    print('2 restore default')
    pick = ''
    while pick not in ('1', '2'):
        pick = input('pick 1 or 2 ').strip()
    action = 'install' if pick == '1' else 'remove'
    color = None
    if action == 'install':
        color = color_bytes(input('give a hex ').strip())
    title('finding adb')
    ADB = adb_path()
    DEVICE = discover(60)
    packages = [package for package in PACKAGES if adb('shell', 'pm', 'path', package, check=False).strip().startswith(b'package:')]
    require(packages, 'pavlov is not installed')
    plans = []
    for package in packages:
        title("preparing attachments")
        plan = inspect(package)
        with tempfile.TemporaryDirectory(prefix="pavlov-mods-") as directory:
            temporary = Path(directory).resolve()
            require(temporary.parent == Path(tempfile.gettempdir()).resolve(), "temporary folder could not be prepared")
            plan["payload"] = build(plan["previous"], action, color, temporary)
        if plan["payload"] != plan["previous"]:
            plans.append(plan)
    if plans:
        backup = root / "req/backups" / uuid.uuid4().hex
        for plan in plans:
            directory = backup / plan["package"]
            directory.mkdir(parents=True)
            prepare(plan, plan["payload"], directory)
        title("writing attachments")
        commit(plans)
    title("done")
    print("done")


def entrypoint():
    try:
        main()
        return 0
    except KeyboardInterrupt:
        print('cancelled')
        return 1
    except Exception as error:
        log = root / 'setup-error.log'
        try:
            log.write_text(traceback.format_exc(), encoding='utf-8')
        except OSError:
            pass
        title('failed')
        print('could not finish')
        print(plain(str(error) or 'check the headset cable'))
        print('saved the error log')
        return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint())
