# Chunks and retrieval

How source becomes something searchable, and how it is found again.

## How code is split

Not into arbitrary windows. The [language provider](languages.md) has already extracted
every declaration with its line span, so **a chunk is usually a whole function or
class**.

Files no provider claims, and the gaps between declarations, fall back to line windows:
40 lines with 5 lines of overlap, capped at 4,000 characters.

Two properties matter enough to be tested:

- **`start_line` and `end_line` describe the text that is actually stored.** An earlier
  version cut a window to 1,500 characters while still reporting the full 40-line span.
  A third of one run's chunks were affected, and retrieval labelled every one of them
  `path:start-end` as though it were complete.
- **Oversized units are split, not truncated.** A 900-line class becomes several chunks
  with honest spans, rather than one chunk holding its first 1,500 characters.

## The four chunk types

| Type | Where it comes from | Trusted as evidence? |
|---|---|---|
| `code` | Source, on symbol boundaries | Yes |
| `docstring` | Prose inside the source | As prose |
| `markdown` | READMEs and docs in the repository | As prose |
| `comment` | Comments worth keeping | As prose |

The distinction is enforced by a **retrieval policy**, not by convention. Documentation
generation is code-only: prose is never returned to a writer, even if a caller asks for
it by name. Question answering may see prose, but it arrives labelled *unverified* in
the block itself — because blocks get reordered, truncated and quoted back, so the
label has to travel with the text.

Prose is a **router**, not a source. It is there to name files worth reading.

## Embeddings

Every chunk is embedded and the vector stored as packed float32 on the row.

Search is **exact cosine in numpy** over the rows the SQL filters selected. There is no
index to build, no vector service to run, and no approximation: the filters run in the
database, and the ranking runs in the process over what they narrowed to.

The width of a vector is measured from the model and recorded on the knowledge base,
never configured. See [Models](../getting-started/models.md#there-is-no-embedding-width-setting).

## Finding things again

Retrieval is **hybrid**, and it has to be.

### The vector half

Embeds your question and ranks chunks by cosine similarity. This is the right
instrument for *"where is rate limiting handled"*, where the words you use and the words
in the code have nothing in common.

### The lexical half

Matches names against the symbol table, four ways:

| Route | Example |
|---|---|
| **Exact** | `update_with_detection`, or `FaceTrack.update_with_detection` |
| **Another style** | `updateWithDetection` folds onto the same key |
| **Misspelled** | `update_with_detecton`, within an edit or two |
| **Described** | *"what updates a track with a detection"*, by overlap with the symbol's own words |

No model call. It reads `graph_symbols`, which analysis already built, and maps each hit
to the chunk that spans its declaration.

??? note "Why the lexical half exists at all"
    A bare identifier embeds to its **meaning**. Searching `update_with_detection`
    against a real knowledge base returned six chunks and not one of them was
    `models.py`, where the method is defined — it landed on code that was *about*
    updating detections instead.

    Asked about that function, the answer said it did not exist. The data had been there
    all along; the search could not reach it.

### Fusing them

On **rank**, not score. Cosine distance and "this is literally the name you typed" are
not comparable numbers, so nothing adds them — reciprocal rank fusion exists for
exactly this.

One exception: the top named hit is **pinned** rather than fused. If the chunk
declaring the thing you asked about is present and does not surface, the answer is "not
found" and the reader is told something false.

## Reading a file back

Analysis discards the checkout, so there is no file on disk to open. What the source
viewer shows is a **reconstruction from stored chunks**.

Chunks overlap in places and leave holes in others, so a file comes back as *segments*
rather than a string. A hole is a segment of its own, naming the lines it spans — because
splicing the next chunk onto the last would render code in an order that does not exist
in the file.

A file that was seen but kept nothing comes back marked `indexed: false`, and the tree
lists it greyed rather than dropping it. "We read this and have nothing to show" and "no
such file" are different answers, and a reader who cannot find `README.md` in the tree
would conclude the wrong one.
