import os
import uvicorn

def main():
    print("=" * 75)
    print("  BRIGHTLOOP SOFTWARE — SUBSCRIPTION MANAGEMENT SYSTEM")
    print("  Odoo x Make-A-Thon Edition (Full-Stack Backend + Interactive UI)")
    print("=" * 75)
    print("\n  • Web Portal & Demo Center : http://127.0.0.1:8000")
    print("  • Interactive OpenAPI Docs : http://127.0.0.1:8000/docs")
    print("\nPre-configured Demo Accounts:")
    print("  • Admin                  : admin@brightloop.com / BrightloopAdmin#2026")
    print("  • Staff                  : staff@brightloop.com / BrightloopStaff#2026")
    print("  • Customer (Enterprise)  : acme@corp.com        / CustomerPass#2026")
    print("  • Customer (Retail Shop) : retail@shop.com      / CustomerPass#2026")
    print("=" * 75)
    print("Press CTRL+C to stop the server.\n")

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "0") == "1"
    uvicorn.run("backend.app.main:app", host=host, port=port, reload=reload)

if __name__ == "__main__":
    main()
