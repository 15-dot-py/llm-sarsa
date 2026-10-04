import type { Metadata } from 'next';
import './globals.css';
import './workspace.css';
import './presentation-theme.css';
export const metadata: Metadata = {
  title: '深谋远虑 · 营销决策工作台',
  description: '比较营销动作、记录经营结果的营销决策工作台。',
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
