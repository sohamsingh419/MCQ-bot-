from telegram.ext import ApplicationBuilder

builder = ApplicationBuilder()
for name in dir(builder):
    if "update" in name.lower() or "timeout" in name.lower() or "pool" in name.lower():
        print(name)
