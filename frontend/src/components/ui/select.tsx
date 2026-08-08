import * as React from 'react';
import { cn } from '@/lib/utils';

// `<select>` nativo estilizado, não Radix Select — evita a classe de bugs
// registrada em memória do projeto irmão (race em formulário aninhado,
// só reproduzível em browser real, não pego por jsdom). Pra um dropdown
// simples (plataforma, provider) o nativo já cobre bem o caso de uso.
export type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(({ className, children, ...props }, ref) => {
  return (
    <select
      className={cn(
        'flex h-10 w-full rounded-md border border-border bg-[hsl(var(--input))] px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className
      )}
      ref={ref}
      {...props}
    >
      {children}
    </select>
  );
});
Select.displayName = 'Select';

export { Select };
