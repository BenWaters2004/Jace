import { Fragment, useMemo, useState } from "react";
import type { ReactNode } from "react";

interface ChatRichContentProps {
  content: string;
  messageId: string;
  streaming?: boolean;
}

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; lines: string[] }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "quote"; lines: string[] }
  | { kind: "code"; language: string; code: string }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "rule" };

function isBlankLine(line: string) {
  return line.trim().length === 0;
}

function isFenceStart(line: string) {
  return /^\s*```/.test(line);
}

function isHeading(line: string) {
  return /^\s{0,3}#{1,6}\s+/.test(line);
}

function isQuote(line: string) {
  return /^\s*>\s?/.test(line);
}

function isUnorderedList(line: string) {
  return /^\s*[-*+]\s+/.test(line);
}

function isOrderedList(line: string) {
  return /^\s*\d+\.\s+/.test(line);
}

function isRule(line: string) {
  return /^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line);
}

function parseTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function isTableDivider(line: string) {
  return /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(line);
}

function isTableStart(lines: string[], index: number) {
  return (
    index + 1 < lines.length &&
    lines[index].includes("|") &&
    isTableDivider(lines[index + 1])
  );
}

function startsSpecialBlock(lines: string[], index: number) {
  const line = lines[index] ?? "";
  return (
    isFenceStart(line) ||
    isHeading(line) ||
    isQuote(line) ||
    isUnorderedList(line) ||
    isOrderedList(line) ||
    isRule(line) ||
    isTableStart(lines, index)
  );
}

function normalise(text: string) {
  return text.replace(/\r\n?/g, "\n");
}

function parseBlocks(content: string): Block[] {
  const lines = normalise(content).split("\n");
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index] ?? "";

    if (isBlankLine(line)) {
      index += 1;
      continue;
    }

    if (isFenceStart(line)) {
      const language = line.replace(/^\s*```/, "").trim().toLowerCase();
      index += 1;
      const codeLines: string[] = [];

      while (index < lines.length && !isFenceStart(lines[index] ?? "")) {
        codeLines.push(lines[index] ?? "");
        index += 1;
      }

      if (index < lines.length && isFenceStart(lines[index] ?? "")) {
        index += 1;
      }

      blocks.push({
        kind: "code",
        language: language || "text",
        code: codeLines.join("\n"),
      });
      continue;
    }

    if (isTableStart(lines, index)) {
      const header = parseTableRow(lines[index] ?? "");
      index += 2;
      const rows: string[][] = [];

      while (index < lines.length && (lines[index] ?? "").includes("|")) {
        rows.push(parseTableRow(lines[index] ?? ""));
        index += 1;
      }

      blocks.push({
        kind: "table",
        header,
        rows,
      });
      continue;
    }

    if (isHeading(line)) {
      const match = line.match(/^(\s{0,3})(#{1,6})\s+(.*)$/);
      blocks.push({
        kind: "heading",
        level: match?.[2]?.length ?? 1,
        text: match?.[3] ?? line.trim(),
      });
      index += 1;
      continue;
    }

    if (isQuote(line)) {
      const quoteLines: string[] = [];
      while (index < lines.length && isQuote(lines[index] ?? "")) {
        quoteLines.push((lines[index] ?? "").replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push({
        kind: "quote",
        lines: quoteLines,
      });
      continue;
    }

    if (isUnorderedList(line) || isOrderedList(line)) {
      const ordered = isOrderedList(line);
      const items: string[] = [];
      while (
        index < lines.length &&
        (ordered
          ? isOrderedList(lines[index] ?? "")
          : isUnorderedList(lines[index] ?? ""))
      ) {
        items.push(
          (lines[index] ?? "").replace(
            ordered ? /^\s*\d+\.\s+/ : /^\s*[-*+]\s+/,
            "",
          ),
        );
        index += 1;
      }

      blocks.push({
        kind: "list",
        ordered,
        items,
      });
      continue;
    }

    if (isRule(line)) {
      blocks.push({ kind: "rule" });
      index += 1;
      continue;
    }

    const paragraphLines: string[] = [];
    while (
      index < lines.length &&
      !isBlankLine(lines[index] ?? "") &&
      !startsSpecialBlock(lines, index)
    ) {
      paragraphLines.push(lines[index] ?? "");
      index += 1;
    }

    if (paragraphLines.length > 0) {
      blocks.push({
        kind: "paragraph",
        lines: paragraphLines,
      });
    }
  }

  return blocks;
}

type InlinePatternKind =
  | "markdown-link"
  | "auto-link"
  | "inline-code"
  | "strong"
  | "em";

const INLINE_PATTERNS: Array<{
  kind: InlinePatternKind;
  regex: RegExp;
}> = [
  {
    kind: "markdown-link",
    regex: /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/,
  },
  {
    kind: "inline-code",
    regex: /`([^`]+)`/,
  },
  {
    kind: "strong",
    regex: /\*\*([^*]+)\*\*/,
  },
  {
    kind: "strong",
    regex: /__([^_]+)__/,
  },
  {
    kind: "em",
    regex: /\*([^*\n]+)\*/,
  },
  {
    kind: "em",
    regex: /_([^_\n]+)_/,
  },
  {
    kind: "auto-link",
    regex: /https?:\/\/[^\s<]+[^\s<.,:;"')\]]/,
  },
];

function richLinkClass(label: string, auto = false) {
  if (/^\[?\d{1,3}\]?$/.test(label.trim())) {
    return "rich-citation-link";
  }

  return auto ? "rich-external-link" : "rich-external-link";
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  if (!text) return [];

  const nodes: ReactNode[] = [];
  let remaining = text;
  let part = 0;

  while (remaining.length > 0) {
    let bestMatch: RegExpMatchArray | null = null;
    let bestKind: InlinePatternKind | null = null;

    for (const pattern of INLINE_PATTERNS) {
      const match = remaining.match(pattern.regex);
      if (!match || match.index == null) continue;
      if (!bestMatch || match.index < (bestMatch.index ?? Number.MAX_SAFE_INTEGER)) {
        bestMatch = match;
        bestKind = pattern.kind;
      }
    }

    if (!bestMatch || bestMatch.index == null || !bestKind) {
      nodes.push(remaining);
      break;
    }

    if (bestMatch.index > 0) {
      nodes.push(remaining.slice(0, bestMatch.index));
    }

    const fullMatch = bestMatch[0];
    const tokenKey = `${keyPrefix}-${part}`;
    part += 1;

    if (bestKind === "markdown-link") {
      const label = bestMatch[1] ?? fullMatch;
      const href = bestMatch[2] ?? "#";
      nodes.push(
        <a
          key={tokenKey}
          className={richLinkClass(label)}
          href={href}
          target="_blank"
          rel="noreferrer"
          title={href}
        >
          {renderInline(label, `${tokenKey}-label`)}
        </a>,
      );
    } else if (bestKind === "auto-link") {
      nodes.push(
        <a
          key={tokenKey}
          className={richLinkClass(fullMatch, true)}
          href={fullMatch}
          target="_blank"
          rel="noreferrer"
          title={fullMatch}
        >
          {fullMatch}
        </a>,
      );
    } else if (bestKind === "inline-code") {
      nodes.push(
        <code key={tokenKey} className="rich-inline-code">
          {bestMatch[1] ?? fullMatch}
        </code>,
      );
    } else if (bestKind === "strong") {
      nodes.push(
        <strong key={tokenKey}>
          {renderInline(bestMatch[1] ?? fullMatch, `${tokenKey}-strong`)}
        </strong>,
      );
    } else if (bestKind === "em") {
      nodes.push(
        <em key={tokenKey}>
          {renderInline(bestMatch[1] ?? fullMatch, `${tokenKey}-em`)}
        </em>,
      );
    }

    remaining = remaining.slice(bestMatch.index + fullMatch.length);
  }

  return nodes;
}

function CopyTextButton({
  value,
  label = "Copy",
}: {
  value: string;
  label?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      if (!navigator?.clipboard?.writeText) return;
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Clipboard access may be denied; fail silently.
    }
  }

  return (
    <button
      type="button"
      className="rich-copy-button"
      onClick={handleCopy}
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
    >
      {copied ? "Copied" : label}
    </button>
  );
}

function ParagraphBlock({
  lines,
  id,
}: {
  lines: string[];
  id: string;
}) {
  return (
    <p className="rich-paragraph">
      {lines.map((line, index) => (
        <Fragment key={`${id}-${index}`}>
          {renderInline(line, `${id}-${index}`)}
          {index < lines.length - 1 && <br />}
        </Fragment>
      ))}
    </p>
  );
}

function CodeBlock({
  code,
  language,
}: {
  code: string;
  language: string;
}) {
  const lineCount = code ? code.split("\n").length : 0;
  const isStructured =
    ["json", "yaml", "yml", "xml", "html"].includes(language) &&
    lineCount >= 14;

  const body = (
    <div className="rich-code-block">
      <div className="rich-code-header">
        <span>{language || "text"}</span>
        <CopyTextButton value={code} />
      </div>
      <pre className="rich-code-pre">
        <code>{code}</code>
      </pre>
    </div>
  );

  if (!isStructured) return body;

  return (
    <details className="rich-structured-block">
      <summary>
        <span>
          {language.toUpperCase()} · {lineCount} lines
        </span>
        <CopyTextButton value={code} label="Copy" />
      </summary>
      <div className="rich-structured-body">{body}</div>
    </details>
  );
}

function renderBlock(block: Block, key: string): ReactNode {
  switch (block.kind) {
    case "heading": {
      const className = `rich-heading rich-heading-${block.level}`;
      switch (block.level) {
        case 1:
          return (
            <h1 key={key} className={className}>
              {renderInline(block.text, key)}
            </h1>
          );
        case 2:
          return (
            <h2 key={key} className={className}>
              {renderInline(block.text, key)}
            </h2>
          );
        case 3:
          return (
            <h3 key={key} className={className}>
              {renderInline(block.text, key)}
            </h3>
          );
        case 4:
          return (
            <h4 key={key} className={className}>
              {renderInline(block.text, key)}
            </h4>
          );
        case 5:
          return (
            <h5 key={key} className={className}>
              {renderInline(block.text, key)}
            </h5>
          );
        default:
          return (
            <h6 key={key} className={className}>
              {renderInline(block.text, key)}
            </h6>
          );
      }
    }
    case "paragraph":
      return <ParagraphBlock key={key} lines={block.lines} id={key} />;
    case "list": {
      const ListTag = block.ordered ? "ol" : "ul";
      return (
        <ListTag key={key} className="rich-list">
          {block.items.map((item, index) => (
            <li key={`${key}-${index}`}>
              {renderInline(item, `${key}-${index}`)}
            </li>
          ))}
        </ListTag>
      );
    }
    case "quote":
      return (
        <blockquote key={key} className="rich-quote">
          {block.lines.map((line, index) => (
            <Fragment key={`${key}-${index}`}>
              {renderInline(line, `${key}-${index}`)}
              {index < block.lines.length - 1 && <br />}
            </Fragment>
          ))}
        </blockquote>
      );
    case "code":
      return (
        <CodeBlock
          key={key}
          code={block.code}
          language={block.language}
        />
      );
    case "table":
      return (
        <div key={key} className="rich-table-wrap">
          <table className="rich-table">
            <thead>
              <tr>
                {block.header.map((cell, index) => (
                  <th key={`${key}-head-${index}`}>
                    {renderInline(cell, `${key}-head-${index}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={`${key}-row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${key}-row-${rowIndex}-${cellIndex}`}>
                      {renderInline(
                        cell,
                        `${key}-row-${rowIndex}-${cellIndex}`,
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "rule":
      return <hr key={key} className="rich-rule" />;
  }
}

export function ChatRichContent(props: ChatRichContentProps) {
  const blocks = useMemo(
    () => parseBlocks(props.content || ""),
    [props.content],
  );

  return (
    <div
      className={`rich-message-content ${props.streaming ? "streaming" : ""}`}
    >
      {blocks.map((block, index) =>
        renderBlock(block, `${props.messageId}-${index}`),
      )}
      {props.streaming && (
        <span className="rich-stream-caret" aria-hidden="true" />
      )}
    </div>
  );
}
