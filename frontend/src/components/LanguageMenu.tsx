import React from "react";
import { LANGS, getLang, setLang, tr, type Lang } from "../i18n";

/** Dil seçici: seçim anında arayüze uygulanır ve bu bilgisayarda hatırlanır. */
export function LanguageMenu({ onChange }: { onChange: (lang: Lang) => void }) {
  const [open, setOpen] = React.useState(false);
  const holder = React.useRef<HTMLDivElement>(null);
  const current = getLang();

  React.useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => { if (!holder.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); };
  }, [open]);

  return <div className="lang-menu" ref={holder}>
    <button type="button" className="lang-button" aria-haspopup="menu" aria-expanded={open} aria-label={tr.languageLabel} title={tr.languageLabel} onClick={() => setOpen(value => !value)}>
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18" /></svg>
      <span>{current.toUpperCase()}</span>
    </button>
    <div className={`lang-list${open ? " open" : ""}`} role="menu" aria-hidden={!open}>
      {LANGS.map(item => <button key={item.code} type="button" role="menuitemradio" aria-checked={item.code === current} tabIndex={open ? 0 : -1}
        onClick={() => { setLang(item.code); onChange(item.code); setOpen(false); }}>
        <span>{item.name}</span><small>{item.code.toUpperCase()}</small>
      </button>)}
    </div>
  </div>;
}
