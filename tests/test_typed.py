import asyncio
from pyrail.irail import iRail


async def main():
    async with iRail() as client:
        stations = await client.get_stations()
        if stations:
            print(f"Total stations: {len(stations)}")


# Run the async function using asyncio.run()
asyncio.run(main())
