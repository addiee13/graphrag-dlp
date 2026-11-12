import { describe, expect, it } from "vitest";
import { readEvents } from "./api";

describe("SSE transport", () => {
  it("decodes fragmented UTF-8, CRLF, comments, multiline JSON and a final event without a newline", async () => {
    const bytes = new TextEncoder().encode(
      ':keepalive\r\nevent: token\r\ndata: {"delta":\r\ndata: "café"}\r\n\r\nevent: done\ndata: {"status":"complete"}',
    );
    const events: unknown[] = [];
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
        controller.close();
      },
    });
    await readEvents(stream, (event) => events.push(event));
    expect(events).toEqual([
      { event: "token", data: { delta: "café" } },
      { event: "done", data: { status: "complete" } },
    ]);
  });
  it("rejects malformed event data rather than treating it as a successful answer", async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode("event: token\ndata: not-json\n\n"),
        );
        controller.close();
      },
    });
    await expect(readEvents(stream, () => {})).rejects.toThrow();
  });
  it("cancels the underlying reader when its session is aborted", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
    });
    const controller = new AbortController();
    const reading = readEvents(stream, () => {}, controller.signal);
    controller.abort();
    await reading.catch(() => {});
    expect(cancelled).toBe(true);
  });
});
