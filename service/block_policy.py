"""Per-block embedding text policy from D-006; called by service/chunk.py chunk_blocks."""


def embed_text_for(block_type, *, text="", caption=None, header_row=None) -> str | None:
    """Select text in O(block size); None/empty captions and headers are absent.

    Header rows contain string cells. Supplied text is preserved without stripping.
    """
    if block_type == 'code':
        return None
    if block_type == 'figure':
        return caption or None
    if block_type == 'table':
        header = ' | '.join(header_row) if header_row is not None else ''
        parts = [part for part in (caption, header) if part]
        return '\n'.join(parts) if parts else None
    if block_type in ('caption', 'paragraph'):
        return text
    raise ValueError(f'Unknown block type: {block_type!r}')
