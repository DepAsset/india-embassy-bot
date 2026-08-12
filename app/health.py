from aiohttp import web


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "india-embassy-bot"})


async def start_health_server(host: str, port: int) -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    return runner
