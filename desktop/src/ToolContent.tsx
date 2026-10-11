import Markdown from 'react-markdown';
import type { ToolPart } from '../electron/activity';

/**
 * Render one recorded tool result in native order.
 *
 * Text parts use normal Markdown typography; image parts become a bounded
 * preview with an open/save attachment link (never a printed base64 string);
 * unknown parts fall back to an explicit readable note. Raw protocol fields
 * stay in the surrounding disclosure, not in this readable body.
 */
export function ToolContent({ parts }: { parts: ToolPart[] }) {
  if (!parts.length) return null;

  return <div className="tool-content">{parts.map((part, index) => {
    if (part.type === 'image') {
      const data = part.data ? `data:${part.mime || 'image/png'};base64,${part.data}` : undefined;
      const source = data ?? part.url;
      const label = `Tool image${part.mime ? ` (${part.mime})` : ''}`;
      // A reserved image box keeps asynchronous loading from moving the reading position.
      return <figure className="tool-image" key={index}>
        {data
          ? <img src={data} alt={label} loading="lazy"/>
          : <span className="tool-attachment">{source
            ? 'Image attachment recorded as a link (not loaded in the reader).'
            : 'Image attachment recorded; the image data is unavailable.'}</span>}
        {source && <figcaption><a href={source} download={`tool-image-${index + 1}`}>Open or save image</a>{part.mime && <span>{part.mime}</span>}</figcaption>}
      </figure>;
    }

    if (part.type === 'unknown') {
      return <p className="tool-unknown" key={index}>Unsupported tool content ({part.label || 'unknown'}). Raw details remain in the record below.</p>;
    }

    if (!part.text.trim()) return null;
    return <div className="tool-text" key={index}><Markdown skipHtml
      components={{ a: ({ children }) => <span>{children}</span>, img: () => <span>[External image omitted]</span> }}>{part.text}</Markdown></div>;
  })}</div>;
}
