import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Navbar } from './Navbar';

vi.mock('next/navigation', () => ({
  usePathname: () => '/professional',
}));

describe('Navbar Component', () => {
  afterEach(cleanup);

  const mockUser = {
    id: 101,
    email: 'counsel@highcourt.nic.in',
    role: 'lawyer' as const,
  };

  it('renders brand identity and professional mode navigation links', () => {
    render(<Navbar user={mockUser} />);

    expect(screen.getByText('LexIntel AI')).toBeInTheDocument();
    expect(screen.getByText('Professional Mode')).toBeInTheDocument();

    expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Text Query' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Upload Brief' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Analytics' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'History' })).toBeInTheDocument();
  });

  it('displays authenticated user email and role badge', () => {
    render(<Navbar user={mockUser} />);

    expect(screen.getByText('counsel@highcourt.nic.in')).toBeInTheDocument();
    expect(screen.getByText('lawyer')).toBeInTheDocument();
  });

  it('triggers onLogout callback when sign out button is clicked', () => {
    const handleLogout = vi.fn();
    render(<Navbar user={mockUser} onLogout={handleLogout} />);

    const signoutBtn = screen.getByRole('button', { name: /Sign out/i });
    fireEvent.click(signoutBtn);

    expect(handleLogout).toHaveBeenCalledTimes(1);
  });

  it('toggles mobile menu on hamburger button click', () => {
    render(<Navbar user={mockUser} />);

    const hamburgerBtn = screen.getByRole('button', { name: /Toggle navigation menu/i });
    expect(hamburgerBtn).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(hamburgerBtn);
    expect(hamburgerBtn).toHaveAttribute('aria-expanded', 'true');
  });
});
