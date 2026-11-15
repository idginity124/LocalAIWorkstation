import React from "react";

type Props = Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, "value"> & {
  value: string;
  maxHeight?: number;
};

/** Keeps chat composers compact while giving longer prompts room to grow. */
export function AutoGrowTextarea({ value, maxHeight = 152, style, ...props }: Props) {
  const elementRef = React.useRef<HTMLTextAreaElement>(null);
  React.useLayoutEffect(() => {
    const node = elementRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, maxHeight)}px`;
    node.style.overflowY = node.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [value, maxHeight]);
  return <textarea {...props} ref={elementRef} value={value} style={style} />;
}
