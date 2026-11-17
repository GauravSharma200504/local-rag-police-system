import { render, screen, fireEvent } from "@testing-library/react";
import { CitationText } from "@/components/CitationText";
import type { Citation } from "@/types";

const cites: Citation[] = [
  { label: "S1", chunk_id: "c1", document_id: "d1", document_title: "FIR", page: 2, passage: "registered at 10:05 PM", support: 0.9 },
];

describe("CitationText", () => {
  it("renders only validated citation labels as clickable chips", () => {
    const onCite = vi.fn();
    render(<CitationText text="The FIR was registered at 10:05 PM [S1]. Unknown claim [S9]." citations={cites} onCite={onCite} />);
    const chip = screen.getByRole("button", { name: "S1" });
    fireEvent.click(chip);
    expect(onCite).toHaveBeenCalledWith(cites[0]);
    expect(screen.queryByRole("button", { name: "S9" })).not.toBeInTheDocument();
    expect(screen.queryByText(/\[S9\]/)).not.toBeInTheDocument();
  });

  it("flags unsupported sentences", () => {
    render(<CitationText text="The accused confessed to the crime." citations={[]} unsupported={["The accused confessed to the crime."]} onCite={() => {}} />);
    expect(screen.getByTitle(/could not be verified/)).toBeInTheDocument();
  });
});
