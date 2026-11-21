"""End-to-end smoke test: clip/photo -> diagnosis -> top-3 offers -> real checkout continue_url.
Never completes a purchase. Usage: python scripts/smoke_test.py path/to/clip.mp4"""
import asyncio
import json
import mimetypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from app import pipeline  # noqa: E402
from app.shop_mcp import ShopMCP  # noqa: E402


async def main(path: str):
    mime = mimetypes.guess_type(path)[0] or "video/mp4"
    res = await pipeline.run(path, mime)
    d = res["diagnosis"]
    print(f"DIAGNOSIS: {d['item']} | part: {d['broken_part']} | buy: {d['replace']}")
    print("timings:", json.dumps(res["timings"]))
    for i, p in enumerate(res["top"], 1):
        print(f"  {i}. {p['title'][:70]}  ${p['price_minor']/100:.2f}  fit={p.get('fit')}  [{p['seller_name']}]")
        print(f"     {p['reason']}")
    if res["top"]:
        p = res["top"][0]
        shop = ShopMCP()
        co = await shop.create_checkout(p["shop"], p["variant_id"])
        await shop.aclose()
        print("checkout status:", co.get("status"))
        print("continue_url:", co.get("continue_url"))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
