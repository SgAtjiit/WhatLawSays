// The companion's answers arrive as plain text with a little structure:
// paragraphs, "- " or "1. " lists, **bold**, "quoted statute", and [n]
// citation markers. This turns that text into data the page renders as React
// nodes. Nothing in it is ever treated as HTML.

const LIST_ITEM = /^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/;
// [3], **bold**, or a quoted phrase of three or more words.
const INLINE = /\[(\d+)\]|\*\*([^*]+)\*\*|["“]([^"”\n]+?(?:\s+[^"”\n]+?){2,})["”]/g;

/** Inline pieces: { text } | { bold } | { quote } | { cite: n }. */
export function parseInline(line) {
  const pieces = [];
  let last = 0;
  for (const match of line.matchAll(INLINE)) {
    if (match.index > last) pieces.push({ text: line.slice(last, match.index) });
    if (match[1]) pieces.push({ cite: Number(match[1]) });
    else if (match[2]) pieces.push({ bold: match[2] });
    else pieces.push({ quote: match[3] });
    last = match.index + match[0].length;
  }
  if (last < line.length) pieces.push({ text: line.slice(last) });
  return pieces;
}

/** Blocks: { type: "p", inline } | { type: "ul" | "ol", items: [inline] }. */
export function parseAnswer(text) {
  const blocks = [];
  for (const chunk of (text || "").split(/\n\s*\n/)) {
    const lines = chunk.split("\n").filter((line) => line.trim());
    let paragraph = [];
    let list = null;
    const endParagraph = () => {
      if (paragraph.length) blocks.push({ type: "p", inline: parseInline(paragraph.join(" ")) });
      paragraph = [];
    };
    const endList = () => {
      if (list) blocks.push(list);
      list = null;
    };
    for (const line of lines) {
      const item = line.match(LIST_ITEM);
      if (item) {
        endParagraph();
        const type = item[1] ? "ol" : "ul";
        if (!list || list.type !== type) {
          endList();
          list = { type, items: [] };
        }
        list.items.push(parseInline(item[2].trim()));
      } else if (list && /^\s{2,}/.test(line)) {
        // A wrapped continuation of the previous list item.
        list.items[list.items.length - 1].push({ text: ` ${line.trim()}` });
      } else {
        endList();
        paragraph.push(line.trim());
      }
    }
    endParagraph();
    endList();
  }
  return blocks;
}

/** Everything the person said in a conversation, for the full scenario analysis. */
export function situationFrom(messages) {
  return messages
    .filter((message) => message.role === "user")
    .map((message) => message.content.trim())
    .join("\n\n");
}
