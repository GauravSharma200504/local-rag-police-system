import { render, screen, fireEvent } from "@testing-library/react";
import { EvidencePanel } from "@/components/EvidencePanel";
import type { Message } from "@/types";

const msg: Message = {
  id: "m1", role: "assistant", content: "x [S1].", abstained: false, created_at: "",
  citations: [{ label: "S1", chunk_id: "c1", document_id: "d1", document_title: "Evidence Report", doc_type: "Evidence Report", page: 1, passage: "black helmet found", support: 0.8 }],
  retrieval: { config: "proposed", sources: [{ label: "S1", chunk_id: "c1", document_id: "d1", document_title: "Evidence Report", filename: "Evidence_Report.pdf", doc_type: "Evidence Report", page_start: 1, page_end: 1, heading: null, section_number: null, text: "black helmet found near culvert", scores: { dense_rank: 1, dense_similarity: 0.71, rrf: 0.03, rerank: 4.2 } }] },
};

describe("EvidencePanel", () => {
  it("shows citations with page and opens the source", () => {
    const onOpen = vi.fn();
    render(<EvidencePanel message={msg} onOpen={onOpen} />);
    expect(screen.getByText("Evidence Report")).toBeInTheDocument();
    expect(screen.getByText(/page 1/)).toBeInTheDocument();
    expect(screen.getByText(/Documentary evidence/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/black helmet found/));
    expect(onOpen).toHaveBeenCalledWith(msg.citations[0]);
  });

  it("shows retrieval stage scores", () => {
    render(<EvidencePanel message={msg} onOpen={() => {}} />);
    fireEvent.click(screen.getByText(/Retrieved \(1\)/));
    expect(screen.getByText(/rerank 4.20/)).toBeInTheDocument();
  });
});
