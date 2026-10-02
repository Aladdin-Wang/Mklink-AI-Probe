/** Commas select alternatives; whitespace requires every word in an alternative. */
export function matchesSignal(query: string, ...labels: string[]): boolean {
  const alternatives = query.toLocaleLowerCase().split(/[,，;；\n]+/).map(term=>term.trim()).filter(Boolean)
  const text = labels.join(' ').toLocaleLowerCase()
  return !alternatives.length || alternatives.some(term=>term.split(/\s+/).every(word=>text.includes(word)))
}
