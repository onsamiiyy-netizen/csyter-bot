import asyncio
import worker_bot
import admin_bot

async def run():
    worker_app = await worker_bot.main()
    admin_app = await admin_bot.main()
    print("оба бота запущены")
    try:
        await asyncio.Event().wait()
    finally:
        await worker_app.updater.stop()
        await worker_app.stop()
        await worker_app.shutdown()
        await admin_app.updater.stop()
        await admin_app.stop()
        await admin_app.shutdown()

if __name__ == "__main__":
    asyncio.run(run())
