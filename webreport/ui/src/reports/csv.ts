/**
 * RFC 4180 CSV built client-side from the table model.
 *
 * Cells are written faithfully: strings verbatim (including ones that start
 * with `=`, `+`, `-` or `@` - the file mirrors the data, it does not rewrite
 * it), numbers through `String`, booleans as `true`/`false`, `null` as an
 * empty field, nested values as JSON. A cell containing a quote, a comma,
 * CR or LF is wrapped in quotes with inner quotes doubled; records end with
 * CRLF and the text starts with a UTF-8 BOM so spreadsheets read Cyrillic.
 */

import type { Row } from "./tableModel";

const BOM = "\uFEFF";
const NEEDS_QUOTES = /[",\r\n]/;

export function csvCell(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  const text =
    typeof value === "string"
      ? value
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
  return NEEDS_QUOTES.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function buildCsv(columns: string[], rows: Row[]): string {
  const lines = [columns.map(csvCell).join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => csvCell(row[column])).join(","));
  }
  return `${BOM}${lines.join("\r\n")}\r\n`;
}
