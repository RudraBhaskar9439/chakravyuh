import { NextResponse } from "next/server";

export function GET() {
  return NextResponse.json(
    {
      status: "ok",
      service: "chakravyuh-web",
    },
    {
      headers: {
        "Cache-Control": "no-store",
      },
    },
  );
}
