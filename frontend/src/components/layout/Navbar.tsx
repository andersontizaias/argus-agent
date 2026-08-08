import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Moon, Settings, Sun, TestTubeDiagonal } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTheme } from '@/lib/useTheme';
import { useHealth } from '@/lib/queries';
import { Button } from '@/components/ui/button';

function HealthDot() {
  const { data } = useHealth();
  const ok = data?.status === 'ok';
  return (
    <span
      title={ok ? 'Ambiente ok' : 'Ambiente degradado'}
      className={cn(
        'inline-block h-2 w-2 rounded-full',
        ok ? 'bg-[hsl(var(--good))]' : 'bg-[hsl(var(--warn))]'
      )}
    />
  );
}

export function Navbar() {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();

  const navItemClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
      isActive ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-muted'
    );

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
        <NavLink to="/" className="flex items-center gap-2">
          <img src="/img/logo.png" alt="Argus Agent" className="h-8 w-8 rounded" />
          <span className="text-lg font-semibold tracking-tight">Argus Agent</span>
        </NavLink>

        <nav className="flex items-center gap-1">
          <NavLink to="/runs" className={navItemClass}>
            <TestTubeDiagonal className="h-4 w-4" />
            {t('nav.runs')}
          </NavLink>
          <NavLink to="/config" className={navItemClass}>
            <Settings className="h-4 w-4" />
            {t('nav.config')}
          </NavLink>
        </nav>

        <div className="flex items-center gap-3">
          <HealthDot />
          <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label="Alternar tema">
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </header>
  );
}
