import { Link } from 'react-router-dom';
import { buttonClasses } from '@/components/Button';

export default function Pricing() {
  return (
    <div className="mx-auto max-w-2xl py-6">
      <h1 className="text-3xl font-bold">Pricing</h1>
      <div className="card mt-8 p-8">
        <h2 className="text-xl font-semibold">Plans aren’t available yet</h2>
        <p className="mt-3 leading-relaxed text-mute">
          There’s nothing to buy right now and no usage limits are enforced by this app. Pricing will appear here when plans launch.
        </p>
        <Link to="/app/new" className={buttonClasses('primary', 'md', 'mt-6')}>Create a Reel</Link>
      </div>
    </div>
  );
}
