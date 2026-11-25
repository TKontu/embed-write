// @ts-check
/**
 * ProseMirror schema for the workbench document model (DM-01).
 * Source-convention attrs (marker, setext, fence, ref) record how the Markdown was written so the
 * serializer (DM-02) can reproduce it.
 */
import { Schema } from 'prosemirror-model';

export const schema = new Schema({
  nodes: {
    doc: { content: 'block*' },
    paragraph: { group: 'block', content: 'inline*' },
    heading: {
      group: 'block', content: 'inline*', defining: true,
      attrs: { level: { default: 1 }, setext: { default: false } },
    },
    blockquote: { group: 'block', content: 'block+', defining: true },
    bullet_list: { group: 'block', content: 'list_item+', attrs: { marker: { default: '-' } } },
    ordered_list: { group: 'block', content: 'list_item+', attrs: { start: { default: 1 } } },
    list_item: { content: 'block*', defining: true, attrs: { checked: { default: null } } },
    code_block: {
      group: 'block', content: 'text*', marks: '', code: true, defining: true,
      attrs: { lang: { default: null }, fence: { default: '```' } },
    },
    thematic_break: { group: 'block' },
    html_block: { group: 'block', atom: true, attrs: { value: { default: '' } } },
    table: { group: 'block', content: 'table_row+' },
    table_row: { content: 'table_cell+' },
    table_cell: { content: 'inline*', attrs: { align: { default: null } } },
    front_matter: { group: 'block', atom: true, attrs: { value: { default: '' } } },
    footnote_definition: { group: 'block', content: 'block*', attrs: { label: {} } },
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
