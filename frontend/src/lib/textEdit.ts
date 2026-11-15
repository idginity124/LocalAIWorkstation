/** Preserve the literal old/new strings; no translator or separate text renderer. */
export function textEditPrompt(before: string, after: string): string {
  return `Replace the existing text ${JSON.stringify(before.trim())} with ${JSON.stringify(after.trim())} in the supplied image. ` +
    'Replace the original lettering in place, matching its existing font, weight, color, size, alignment, perspective and background. ' +
    'The old text must disappear completely. Keep exactly one inscription at the original position. Preserve all other text and image details.';
}
