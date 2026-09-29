import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Report } from "../api/types";
import { buildCsv } from "./csv";
import { ReportPreview } from "./ReportPreview";

const base: Report = {
  id: "r1",
  chat_id: "c1",
  title: "Итоги сезона",
  question: "Сколько очков набрали команды?",
  tool: "read_rows",
  args: { table: "results", limit: 10, filters: { season: "2024/25" } },
  generated_at: "2026-09-28T10:15:00Z",
  version: 2,
  saved_at: null,
  row_count: 3,
  created_at: "2026-09-28T10:15:00Z",
  data: [
    { команда: "Альфа", очки: 1234.5678, игры: 100000 },
    { команда: "Бета", очки: -7.25, игры: 42 },
    { команда: "Гамма", очки: 0.1, игры: 7 },
  ],
};

function withData(data: unknown, extra: Partial<Report> = {}): Report {
  return { ...base, ...extra, data };
}

/**
 * jsdom's Blob has no `text()`; read the bytes through FileReader and decode
 * them with the BOM kept so the test can assert it is present.
 */
function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve(
        new TextDecoder("utf-8", { ignoreBOM: true }).decode(
          reader.result as ArrayBuffer,
        ),
      );
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

/** Tooltip text of every bar: carried by the full-height hit rect so it is always hoverable. */
function barTitles(container: HTMLElement): string[] {
  return Array.from(
    container.querySelectorAll(".report-chart__hit title"),
    (title) => title.textContent ?? "",
  );
}

function axisLabels(container: HTMLElement): SVGTextElement[] {
  return Array.from(container.querySelectorAll<SVGTextElement>(".report-chart__label"));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("ReportPreview header", () => {
  it("shows the title, the generation time in ru-RU and the version", () => {
    render(<ReportPreview report={base} />);

    const expected = new Intl.DateTimeFormat("ru-RU", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date("2026-09-28T10:15:00Z"));
    expect(
      screen.getByRole("heading", { level: 2, name: "Итоги сезона" }),
    ).toBeInTheDocument();
    expect(screen.getByText(`Сформирован: ${expected}`)).toBeInTheDocument();
    expect(screen.getByText("Версия 2")).toBeInTheDocument();
  });

  it("falls back to the raw timestamp when it cannot be parsed", () => {
    render(<ReportPreview report={{ ...base, generated_at: "не дата" }} />);

    expect(screen.getByText("Сформирован: не дата")).toBeInTheDocument();
  });

  it("renders «Чат удалён» for an orphan instead of the chat link", () => {
    render(
      <ReportPreview
        report={{ ...base, chat_id: null }}
        orphan
        chatLink={<a href="/chats/c1">Открыть чат</a>}
      />,
    );

    expect(screen.getByText("Чат удалён")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Открыть чат" })).toBeNull();
  });

  it("renders the chat link slot when the report is not orphaned", () => {
    render(
      <ReportPreview
        report={base}
        chatLink={<a href="/chats/c1">Открыть чат</a>}
      />,
    );

    expect(screen.getByRole("link", { name: "Открыть чат" })).toHaveAttribute(
      "href",
      "/chats/c1",
    );
    expect(screen.queryByText("Чат удалён")).toBeNull();
  });
});

describe("ReportPreview parameters", () => {
  it("lists the question, the tool, every argument exactly and the row count", () => {
    render(<ReportPreview report={base} />);

    const params = screen.getByRole("region", { name: "Параметры" });
    const terms = within(params)
      .getAllByRole("term")
      .map((term) => term.textContent);
    expect(terms).toEqual([
      "Запрос",
      "Инструмент",
      "table",
      "limit",
      "filters",
      "Строк",
    ]);
    const definitions = within(params)
      .getAllByRole("definition")
      .map((definition) => definition.textContent);
    expect(definitions).toEqual([
      "Сколько очков набрали команды?",
      "read_rows",
      "results",
      "10",
      '{"season":"2024/25"}',
      "3",
    ]);
  });

  it("shows — when the row count is unknown", () => {
    render(<ReportPreview report={{ ...base, row_count: null }} />);

    const params = screen.getByRole("region", { name: "Параметры" });
    const definitions = within(params).getAllByRole("definition");
    expect(definitions.at(-1)).toHaveTextContent("—");
  });
});

describe("ReportPreview table", () => {
  it("renders every cell value verbatim without grouping or rounding", () => {
    render(<ReportPreview report={base} />);

    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual(["команда", "очки", "игры"]);
    for (const value of [
      "Альфа",
      "1234.5678",
      "100000",
      "Бета",
      "-7.25",
      "42",
      "Гамма",
      "0.1",
      "7",
    ]) {
      expect(within(table).getByText(value)).toBeInTheDocument();
    }
    expect(within(table).queryByText("1 234.5678")).toBeNull();
    expect(within(table).queryByText("100 000")).toBeNull();
  });

  it("uses the union of keys when rows have different column sets", () => {
    render(
      <ReportPreview
        report={withData([
          { a: 1, b: "x" },
          { b: "y", c: 2.5 },
          { c: 3, a: 4 },
        ])}
      />,
    );

    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual(["a", "b", "c"]);
    const rows = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      );
    expect(rows).toEqual([
      ["1", "x", "—"],
      ["—", "y", "2.5"],
      ["4", "—", "3"],
    ]);
  });

  it("renders null as —, booleans as да/нет and nested objects as JSON", () => {
    render(
      <ReportPreview
        report={withData([
          { k: "n", v: null, flag: true, obj: { x: [1, "y"] } },
          { k: "m", v: 0, flag: false, obj: [1, 2] },
        ])}
      />,
    );

    const table = screen.getByRole("table");
    const rows = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      );
    expect(rows).toEqual([
      ["n", "—", "да", '{"x":[1,"y"]}'],
      ["m", "0", "нет", "[1,2]"],
    ]);
  });

  it("scrolls long tables inside the container", () => {
    const rows = Array.from({ length: 500 }, (_, index) => ({
      i: index,
      value: index * 1.5,
    }));
    const { container } = render(<ReportPreview report={withData(rows)} />);

    const wrap = container.querySelector(".report-table-wrap");
    expect(wrap).not.toBeNull();
    expect(wrap).toContainElement(screen.getByRole("table"));
    expect(screen.getAllByRole("row")).toHaveLength(501);
  });
});

describe("ReportPreview CSV", () => {
  const special = [
    {
      name: 'Say "hi", now',
      note: "line1\nline2",
      formula: "=SUM(A1)",
      n: 1234.5678,
      flag: true,
      empty: null,
    },
    { name: "plain", note: "", formula: "+1", n: 100000, flag: false, empty: 0 },
  ];

  it("builds RFC 4180 text with a BOM, CRLF and quoted special cells", () => {
    const columns = ["name", "note", "formula", "n", "flag", "empty"];

    expect(buildCsv(columns, special)).toBe(
      "\uFEFFname,note,formula,n,flag,empty\r\n" +
        '"Say ""hi"", now","line1\nline2",=SUM(A1),1234.5678,true,\r\n' +
        "plain,,+1,100000,false,0\r\n",
    );
  });

  it("downloads the CSV built from the rendered table on click", async () => {
    const createObjectURL = vi.fn<(blob: Blob) => string>(() => "blob:report");
    const revokeObjectURL = vi.fn<(url: string) => void>();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const downloads: string[] = [];
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        downloads.push(this.download);
      });
    const user = userEvent.setup();
    render(<ReportPreview report={withData(special, { id: "abc", version: 3 })} />);

    await user.click(screen.getByRole("button", { name: "Скачать CSV" }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0]?.[0];
    expect(blob).toBeInstanceOf(Blob);
    expect(blob?.type).toBe("text/csv;charset=utf-8");
    expect(await readBlob(blob as Blob)).toBe(
      buildCsv(["name", "note", "formula", "n", "flag", "empty"], special),
    );
    expect(click).toHaveBeenCalledTimes(1);
    expect(downloads).toEqual(["report-abc-v3.csv"]);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:report");
  });
});

describe("ReportPreview chart", () => {
  it("shows the column selector and an SVG bar chart with exact tooltips", async () => {
    const user = userEvent.setup();
    const { container } = render(<ReportPreview report={base} />);

    const select = screen.getByRole("combobox", { name: "Колонка для графика" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["очки", "игры"]);
    expect(
      screen.getByRole("img", { name: "Столбчатая диаграмма: очки" }),
    ).toBeInTheDocument();
    expect(barTitles(container)).toEqual([
      "Альфа: 1234.5678",
      "Бета: -7.25",
      "Гамма: 0.1",
    ]);
    expect(container.querySelector("canvas")).toBeNull();

    await user.selectOptions(select, "игры");

    expect(
      screen.getByRole("img", { name: "Столбчатая диаграмма: игры" }),
    ).toBeInTheDocument();
    expect(barTitles(container)).toEqual([
      "Альфа: 100000",
      "Бета: 42",
      "Гамма: 7",
    ]);
  });

  it("labels the axis with the first column's values", () => {
    const { container } = render(<ReportPreview report={base} />);

    const labels = axisLabels(container).map(
      (label) => label.querySelector("tspan")?.textContent,
    );
    expect(labels).toEqual(["Альфа", "Бета", "Гамма"]);
  });

  it("renders a label for every bar of a 500-row table, none dropped", () => {
    const rows = Array.from({ length: 500 }, (_, index) => ({
      метка: `строка ${String(index)}`,
      значение: index * 2.5,
    }));
    const { container } = render(<ReportPreview report={withData(rows)} />);

    const labels = axisLabels(container).map((label) =>
      label.querySelector("title")?.textContent,
    );
    expect(labels).toHaveLength(500);
    expect(labels[0]).toBe("строка 0");
    expect(labels[499]).toBe("строка 499");
    expect(new Set(labels).size).toBe(500);
    expect(barTitles(container)).toHaveLength(500);
    expect(barTitles(container)[137]).toBe("строка 137: 342.5");
  });

  it("keeps the full text of a long label retrievable from the label and the bar tooltip", () => {
    const long =
      "Очень длинное название команды, которое не помещается на оси целиком";
    const { container } = render(
      <ReportPreview
        report={withData([
          { команда: long, очки: 12.5 },
          { команда: "Бета", очки: 3 },
        ])}
      />,
    );

    const [first] = axisLabels(container);
    expect(first?.querySelector("title")?.textContent).toBe(long);
    expect(barTitles(container)[0]).toBe(`${long}: 12.5`);
  });

  it("exposes an exact-value tooltip on a hoverable hit area even for tiny and zero values", () => {
    const { container } = render(
      <ReportPreview
        report={withData([
          { k: "большое", v: 1000000 },
          { k: "крошечное", v: 0.0001 },
          { k: "ноль", v: 0 },
        ])}
      />,
    );

    expect(barTitles(container)).toEqual([
      "большое: 1000000",
      "крошечное: 0.0001",
      "ноль: 0",
    ]);
    const hits = Array.from(
      container.querySelectorAll<SVGRectElement>(".report-chart__hit"),
    );
    expect(hits).toHaveLength(3);
    const heights = hits.map((hit) => Number(hit.getAttribute("height")));
    expect(heights.every((height) => height >= 100)).toBe(true);
    expect(new Set(heights).size).toBe(1);
    const bars = Array.from(
      container.querySelectorAll<SVGRectElement>(".report-chart__bar"),
    );
    expect(bars).toHaveLength(3);
    expect(Number(bars[1]?.getAttribute("height"))).toBeGreaterThanOrEqual(1);
  });

  it("does not render a chart when no numeric column besides the first exists", () => {
    render(
      <ReportPreview
        report={withData([
          { id: 1, name: "a" },
          { id: 2, name: "b" },
        ])}
      />,
    );

    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("does not render a chart when records have no columns", () => {
    render(<ReportPreview report={withData([{}, {}])} />);

    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("treats a column with strings mixed into numbers as non-numeric", () => {
    render(
      <ReportPreview
        report={withData([
          { k: "a", v: 1, w: "1" },
          { k: "b", v: null, w: 2 },
        ])}
      />,
    );

    const select = screen.getByRole("combobox", { name: "Колонка для графика" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["v"]);
  });
});

describe("ReportPreview non-tabular data", () => {
  it("shows «Нет данных» for an empty array", () => {
    render(<ReportPreview report={withData([], { row_count: 0 })} />);

    expect(screen.getByText("Нет данных")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Скачать CSV" })).toBeNull();
  });

  it("shows «Нет данных» for null data", () => {
    render(<ReportPreview report={withData(null, { row_count: null })} />);

    expect(screen.getByText("Нет данных")).toBeInTheDocument();
  });

  it("renders object data as pretty-printed JSON", () => {
    const { container } = render(
      <ReportPreview report={withData({ total: 12.5, by: { a: 1 } })} />,
    );

    const pre = container.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre?.textContent).toBe(
      JSON.stringify({ total: 12.5, by: { a: 1 } }, null, 2),
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders an array of primitives as JSON rather than a table", () => {
    const { container } = render(<ReportPreview report={withData([1, "two", 3])} />);

    expect(container.querySelector("pre")?.textContent).toBe(
      JSON.stringify([1, "two", 3], null, 2),
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders scalar data as its string form", () => {
    render(<ReportPreview report={withData(42.125)} />);

    expect(screen.getByText("42.125")).toBeInTheDocument();
  });
});
