import { Link } from 'react-router-dom';
import { buttonClasses } from '@/components/Button';

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md px-4 py-28 text-center">
      <h1 className="text-4xl font-bold">Page not found</h1>
      <p className="mt-3 text-mute">The page you’re looking for doesn’t exist or has moved.</p>
      <Link to="/app" className={buttonClasses('primary', 'md', 'mt-8')}>Go to dashboard</Link>
    </div>
  );
}
