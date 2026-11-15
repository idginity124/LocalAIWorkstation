import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { Icon, type IconName } from "../Icon";

/** Shared, keyboard-accessible primitives. Page-specific controls can adopt these incrementally. */
export function ActionButton({ variant = "secondary", icon, children, className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  icon?: IconName;
}) {
  return <button {...props} className={`ui-button ui-button--${variant}${className ? ` ${className}` : ""}`}>
    {icon && <Icon name={icon} size={17} />}{children}
  </button>;
}

export function StatusPill({ tone = "neutral", children, className = "", ...props }: HTMLAttributes<HTMLSpanElement> & {
  tone?: "neutral" | "success" | "warning" | "danger";
  children: ReactNode;
}) {
  return <span {...props} className={`ui-status ui-status--${tone}${className ? ` ${className}` : ""}`}>
    <span className="ui-status__dot" aria-hidden="true" />{children}
  </span>;
}

export function SectionHeading({ eyebrow, title, description }: { eyebrow?: string; title: string; description?: string }) {
  return <div className="ui-section-heading">
    {eyebrow && <span className="ui-section-heading__eyebrow">{eyebrow}</span>}
    <h2>{title}</h2>{description && <p>{description}</p>}
  </div>;
}
