# Replace argument values with your actual account credentials
import base64
import os
import asyncio
from pathlib import Path

import pygame
import PIL
from PIL import Image

import novelai
from novelai import NAIClient, Metadata, Host

username = "funplayerggpo@live.com"
password = "Cheese12!"

async def main():
    client = NAIClient(username, password, proxy=None)
    await client.init(timeout=30)
    metadata = Metadata(
        steps=20,
        prompt="1girl",
        negative_prompt="bad anatomy",
        width=512,
        height=512,
        n_samples=1,
    )

    print(f"Estimated Anlas cost: {metadata.calculate_cost(is_opus=False)}")

    # Choose host between "Host.API" and "Host.WEB"
    # Both of two hosts work the same for all actions mentioned below
    output = await client.generate_image(
        metadata, verbose=False, is_opus=True
    )
    for image in output:
        print (len(output[image]))
        path = Path("output")
        path.mkdir(parents=True, exist_ok=True)
        # make the directory if it doesn't exist
        for filename, data in output.items():
            Path(path / filename).write_bytes(data)

asyncio.run(main())