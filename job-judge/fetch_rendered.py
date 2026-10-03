"""헤드리스 브라우저로 공고 페이지를 직접 열어 화면에 보이는 텍스트와 이미지 URL을 꺼내는 도구.

WebFetch/httpx는 서버가 내려준 HTML만 받는다. 공고 본문을 자바스크립트로 나중에 불러오는 페이지(예:
recruiter.co.kr 계열 채용 사이트)나 본문이 통째로 이미지인 공고는 이 방식으로는 제목·마감일 같은 뼈대만 나온다.
그런 경우 이 스크립트가 PC에 설치된 Edge/Chrome을 헤드리스로 띄워 자바스크립트가 실행된 뒤의 DOM을 받고,
본문이 이미지면 이미지를 내려받아 긴 이미지는 읽기 좋은 크기로 잘라 둔다. 이미지 안의 글자는 세션(Claude)이
Read 도구로 이미지를 열어서 읽는다 -- 코드는 글자를 판독하지 않는다.

사용:
    python fetch_rendered.py <url> [--download-dir DIR] [--slice]
"""

import html as html_lib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin

import typer

_BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
_BROWSER_NAMES = ["msedge", "google-chrome", "chromium", "chrome"]

# 긴 공고 이미지를 읽기 도구로 열면 축소돼 글자가 뭉개지므로, 폭 1000px로 줄인 뒤 이 높이로 자른다.
SLICE_WIDTH = 1000
SLICE_HEIGHT = 1500


def find_browser() -> str | None:
    for path in _BROWSER_CANDIDATES:
        if Path(path).exists():
            return path
    for name in _BROWSER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


def render_dom(url: str, browser: str | None = None, timeout: int = 90, budget_ms: int = 20000) -> str:
    """Return the DOM after the page's JavaScript ran (headless --dump-dom)."""
    browser = browser or find_browser()
    if browser is None:
        raise RuntimeError("Edge/Chrome을 찾지 못했다. 설치 경로를 _BROWSER_CANDIDATES에 추가한다.")
    result = subprocess.run(
        [browser, "--headless=new", "--disable-gpu", f"--virtual-time-budget={budget_ms}", "--dump-dom", url],
        capture_output=True,
        timeout=timeout,
    )
    return result.stdout.decode("utf-8", errors="replace")


def visible_text(dom: str) -> str:
    without_code = re.sub(r"<script.*?</script>|<style.*?</style>", " ", dom, flags=re.S)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", without_code))
    return re.sub(r"\s+", " ", text).strip()


def image_urls(dom: str, base_url: str) -> list[str]:
    urls = []
    for src in re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", dom):
        if src.startswith("data:"):
            continue
        full = urljoin(base_url, html_lib.unescape(src))
        if full not in urls:
            urls.append(full)
    return urls


def download_images(urls: list[str], out_dir: Path) -> list[Path]:
    import httpx

    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, url in enumerate(urls):
        response = httpx.get(url, follow_redirects=True, timeout=30)
        response.raise_for_status()
        suffix = Path(url.split("?")[0]).suffix or ".img"
        path = out_dir / f"image_{i}{suffix}"
        path.write_bytes(response.content)
        saved.append(path)
    return saved


def slice_image(path: Path, out_dir: Path) -> list[Path]:
    """Resize to SLICE_WIDTH and cut into SLICE_HEIGHT pieces (needs Pillow)."""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(path).convert("RGB")
    width, height = image.size
    image = image.resize((SLICE_WIDTH, int(height * SLICE_WIDTH / width)))
    pieces = []
    top = 0
    while top < image.height:
        piece = out_dir / f"{path.stem}_part{len(pieces)}.png"
        image.crop((0, top, SLICE_WIDTH, min(image.height, top + SLICE_HEIGHT + 50))).save(piece)
        pieces.append(piece)
        top += SLICE_HEIGHT
    return pieces


def main(
    url: str = typer.Argument(..., help="공고 페이지 URL"),
    download_dir: Path = typer.Option(None, "--download-dir", help="본문 이미지를 내려받을 폴더"),
    slice_images: bool = typer.Option(False, "--slice", help="내려받은 이미지를 읽기 좋은 크기로 자른다 (Pillow 필요)"),
) -> None:
    # Windows 콘솔 기본 인코딩(cp949)에서 한글/특수문자가 깨지지 않게 UTF-8로 고정한다.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    dom = render_dom(url)
    print("[화면 텍스트]")
    print(visible_text(dom))
    images = image_urls(dom, url)
    print("\n[이미지]")
    for image in images:
        print(image)
    if download_dir is not None and images:
        for path in download_images(images, download_dir):
            print("saved:", path)
            if slice_images:
                for piece in slice_image(path, download_dir / "slices"):
                    print("slice:", piece)


if __name__ == "__main__":
    typer.run(main)
