import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TraceEvent } from "../api/client";
import { TraceTimeline } from "./TraceTimeline";

function ev(partial: Partial<TraceEvent> & { stage: string }): TraceEvent {
  return { message: "", ...partial };
}

describe("TraceTimeline", () => {
  it("shows an idle hint when there are no events", () => {
    const { container } = render(<TraceTimeline events={[]} loading={false} />);
    expect(container.textContent).toContain("送出問題後");
  });

  it("narrates page_fetch with the document name and page range", () => {
    const { container } = render(
      <TraceTimeline
        events={[
          ev({
            stage: "page_fetch",
            document_name: "TXC_SOP_2026.pdf",
            start_page: 16,
            end_page: 17
          })
        ]}
        loading={false}
      />
    );
    const text = container.textContent ?? "";
    expect(text).toContain("正在翻閱");
    expect(text).toContain("TXC_SOP_2026.pdf");
    expect(text).toContain("第 16-17 頁");
  });

  it("collapses a single-page range", () => {
    const { container } = render(
      <TraceTimeline
        events={[ev({ stage: "navigation", document_name: "doc.pdf", start_page: 5, end_page: 5 })]}
        loading={false}
      />
    );
    expect(container.textContent).toContain("第 5 頁");
  });

  it("marks only the last step active while loading", () => {
    const { container } = render(
      <TraceTimeline
        events={[ev({ stage: "router" }), ev({ stage: "page_fetch", document_name: "d.pdf" })]}
        loading={true}
      />
    );
    const active = container.querySelectorAll(".trace-step--active");
    expect(active).toHaveLength(1);
    const steps = container.querySelectorAll(".trace-step");
    expect(steps[steps.length - 1].classList.contains("trace-step--active")).toBe(true);
  });

  it("does not mark any step active once loading is complete", () => {
    const { container } = render(
      <TraceTimeline events={[ev({ stage: "synthesis", document_name: "d.pdf" })]} loading={false} />
    );
    expect(container.querySelectorAll(".trace-step--active")).toHaveLength(0);
  });
});
