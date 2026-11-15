"""Publish one test image post to the connected Instagram account.

  uv run python -m probe.publish_test
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from concierge import zernio

OUT = Path(__file__).resolve().parent.parent / "data" / "test_post.jpg"
CAPTION = (
    "Live from the Social GTM Agents Hackathon in Paris today.\n\n"
    "This account is run by an AI event agent built on Zernio. "
    "Comment LINK below and it will DM you automatically.\n\n"
    "#hackathon #AIagents #Paris"
)


def make_image() -> Path:
    OUT.parent.mkdir(exist_ok=True)
    img = Image.new("RGB", (1080, 1080), (238, 64, 36))
    d = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 96)
        small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 48)
    except OSError:
        big = small = ImageFont.load_default()
    d.text((90, 330), "Social GTM\nAgents Hackathon", font=big, fill="white", spacing=20)
    d.text((90, 640), "Paris · 15.11.2026", font=small, fill="white")
    d.text((90, 860), "Comment LINK  →  get a DM", font=small, fill="white")
    img.save(OUT, quality=92)
    return OUT


def main() -> None:
    path = make_image()
    url = zernio.upload_media(str(path), "image/jpeg")
    print("uploaded media")
    account_id = zernio.instagram_account_id()
    res = zernio.publish_post(CAPTION, [{"platform": "instagram", "accountId": account_id}], [url])
    post = res.get("post", res)
    print("post id:", post.get("_id"), "status:", post.get("status"))
    for p in post.get("platforms", []):
        print(" ", p.get("platform"), p.get("status"), p.get("platformPostId"), p.get("platformPostUrl"), p.get("errorMessage", ""))


if __name__ == "__main__":
    main()
