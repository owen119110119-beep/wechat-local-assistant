"""Install fixed SILK wasm package without running npm lifecycle scripts."""
import base64
import hashlib
import io
import json
import pathlib
import tarfile
import urllib.request

root = pathlib.Path(__file__).resolve().parents[1]
metadata = json.load(urllib.request.urlopen("https://registry.npmjs.org/silk-wasm/3.7.1", timeout=30))
assert metadata["version"] == "3.7.1"
assert not metadata.get("dependencies"), "Review transitive dependencies before installing"
url = metadata["dist"]["tarball"]
assert url == "https://registry.npmjs.org/silk-wasm/-/silk-wasm-3.7.1.tgz"
payload = urllib.request.urlopen(url, timeout=60).read(20 * 1024 * 1024)
actual = "sha512-" + base64.b64encode(hashlib.sha512(payload).digest()).decode()
assert actual == metadata["dist"]["integrity"]
target = root / "node_modules" / "silk-wasm"
with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
    for member in archive.getmembers():
        p = pathlib.PurePosixPath(member.name)
        assert p.parts[0] == "package" and ".." not in p.parts and not member.issym() and not member.islnk()
        if member.isfile():
            dest = target.joinpath(*p.parts[1:])
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.extractfile(member).read())
(root / ".runtime" / "silk-install.json").write_text(json.dumps({"version": "3.7.1", "integrity": actual, "source": url, "lifecycle_scripts": False}, indent=2))
print("silk-wasm 3.7.1 integrity verified; lifecycle scripts disabled")
