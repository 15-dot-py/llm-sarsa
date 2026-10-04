import type { Metadata } from 'next';
import './globals.css';
import './workspace.css';
import './presentation-theme.css';
export const metadata: Metadata = {
  title: '三只松鼠 · 深谋远虑营销工作台',
  description: '围绕三只松鼠电商场景，比较营销动作、记录经营结果。',
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
