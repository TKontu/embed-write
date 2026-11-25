// @ts-check
/**
 * ProseMirror schema for the workbench document model (DM-01).
 * Source-convention attrs (marker, setext, fence, ref) record how the Markdown was written so the
 * serializer (DM-02) can reproduce it.
 */
import { Schema } from 'prosemirror-model';

/**
 * NI-01: every block-level node carries `id` (ULID string or null, default null). That is every
 * node in group 'block' plus the non-group structural blocks list_item, table_row and table_cell.
 * Inline nodes, text and doc carry no id. parseMarkdown leaves ids null; serializeMarkdown never
 * emits them (I1: IDs live only in the sidecar, NI-02). See ids.js for assignment.
 */
const ID = { default: null };

export const schema = new Schema({
  nodes: {
    doc: { content: 'block*' },
    paragraph: { group: 'block', content: 'inline*', attrs: { id: ID } },
    heading: {
      group: 'block', content: 'inline*', defining: true,
      attrs: { level: { default: 1 }, setext: { default: false }, id: ID },
    },
    blockquote: { group: 'block', content: 'block+', defining: true, attrs: { id: ID } },
    bullet_list: { group: 'block', content: 'list_item+', attrs: { marker: { default: '-' }, id: ID } },
    ordered_list: { group: 'block', content: 'list_item+', attrs: { start: { default: 1 }, id: ID } },
    list_item: { content: 'block*', defining: true, attrs: { checked: { default: null }, id: ID } },
    code_block: {
      group: 'block', content: 'text*', marks: '', code: true, defining: true,
      attrs: { lang: { default: null }, fence: { default: '```' }, id: ID },
    },
    thematic_break: { group: 'block', attrs: { id: ID } },
    html_block: { group: 'block', atom: true, attrs: { value: { default: '' }, id: ID } },
    table: { group: 'block', content: 'table_row+', attrs: { id: ID } },
    table_row: { content: 'table_cell+', attrs: { id: ID } },
    table_cell: { content: 'inline*', attrs: { align: { default: null }, id: ID } },
    front_matter: { group: 'block', atom: true, attrs: { value: { default: '' }, id: ID } },
    footnote_definition: { group: 'block', content: 'block*', attrs: { label: {}, id: ID } },
    image: {
      group: 'inline', inline: true, atom: true,
      attrs: { src: {}, alt: { default: null }, title: { default: null }, ref: { default: null } },
    },
    hard_break: { group: 'inline', inline: true },
    text: { group: 'inline' },
  },
  marks: {
    link: {
      inclusive: false,
      attrs: { href: {}, title: { default: null }, ref: { default: null } },
    },
    em: { attrs: { marker: { default: '*' } } },
    strong: { attrs: { marker: { default: '*' } } },
    code: { excludes: '_' },
    footnote_reference: { excludes: '_', attrs: { label: {} } },
  },
});
