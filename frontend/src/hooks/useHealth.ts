import { useQuery } from '@tanstack/react-query';
import { getHealth } from '@/api/health';

export const useHealth = () =>
  useQuery({ queryKey: ['health'], queryFn: ({ signal }) => getHealth(signal), staleTime: 30_000, retry: 1 });
