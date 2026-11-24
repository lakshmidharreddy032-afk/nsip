import { useMemo, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import { useSession } from "@/stores/session";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

/** Native PDF rendering with the source line highlighted in the text layer. */
export default function PdfView({ url, highlight }: { url: string; highlight: string | null }) {
  const token = useSession((s) => s.token);
  const [pages, setPages] = useState(0);
  const options = useMemo(() => ({ httpHeaders: { Authorization: `Bearer ${token}` } }), [token]);
  const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
  return (
    <Document file={url} options={options} onLoadSuccess={(d) => setPages(d.numPages)}
      loading={<p className="text-sm text-subtle">Loading PDF…</p>} error={<p className="text-sm text-danger">PDF could not be displayed; extracted text is below.</p>}>
      {Array.from({ length: pages }, (_, i) => (
        <Page key={i} pageNumber={i + 1} width={560} renderAnnotationLayer={false} className="mb-3 overflow-hidden rounded-lg border border-border"
          customTextRenderer={({ str }) => (highlight && str.trim() && highlight.includes(str.trim()) ? `<mark class="source-hl">${esc(str)}</mark>` : esc(str))} />
      ))}
    </Document>
  );
}
