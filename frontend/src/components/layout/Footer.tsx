import { useHealth } from '@/lib/queries';

export function Footer() {
  const { data } = useHealth();
  return (
    <footer className="mx-auto max-w-6xl px-4 py-6 text-center text-xs text-muted-foreground">
      Argus Agent {data?.version ? `v${data.version}` : ''}
    </footer>
  );
}
