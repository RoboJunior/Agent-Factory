import base64

import aiofiles
from openai import AsyncOpenAI

client = AsyncOpenAI(
    base_url="http://localhost:8091/v1",
    api_key="",
)


# Process the invoice and send that extracted data.
async def extract_invoice_details(image_path: str):
    async with aiofiles.open(image_path, mode="rb") as file:
        image_bytes = await file.read()

    image_bs4 = base64.b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:image/png;base64,{image_bs4}"

    response = await client.chat.completions.create(
        model="tencent/HunyuanOCR",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """Extract all the details from the given image""",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri},
                    },
                ],
            }
        ],
    )
    return response.choices[0].message.content
