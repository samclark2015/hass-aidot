import asyncio as aio
from pprint import pprint

from aidot.client import AidotClient
from aidot.device_client import DeviceClient
from aidot.discover import Discover
from aiohttp.client import ClientSession


async def main():
    async with ClientSession() as sess:
        client = AidotClient(sess, "United States", "slc2015@gmail.com", "!JuLy71997@")

        login_info = await client.async_post_login()
        pprint(login_info)

        discover = Discover(login_info, None)

        dinf = await discover.fetch_devices_info()

        pprint(dinf)

        devices = await client.async_get_all_device()
        # pprint(devices)

        light = [
            device
            for device in devices["device_list"]
            if device["name"] == "Smart Light Bulb A19 RGBTW_18"
        ][0]
        pprint(light)

        ip = dinf.get(light["id"])

        device = DeviceClient(light, login_info)
        await device.connect(ip)

        await device.async_turn_on()
        await device.async_set_rgbw((100, 150, 200, 255))  # Example RGBW values


aio.run(main())
