import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../lib/api';
import { useState } from 'react';
import { Server, Plus, Minus, RefreshCw } from 'lucide-react';

interface Worker {
  id: string;
  container_name: string;
  status: string;
  created_at: string;
  executions: number;
}

export function Workers() {
  const queryClient = useQueryClient();
  const [scaleTarget, setScaleTarget] = useState(1);

  // Fetch workers
  const { data: workers, isLoading } = useQuery({
    queryKey: ['workers'],
    queryFn: () => apiClient.listWorkers(),
    refetchInterval: 5000, // Refresh every 5 seconds
  });

  // Fetch worker count
  const { data: countData } = useQuery({
    queryKey: ['worker-count'],
    queryFn: () => apiClient.getWorkerCount(),
    refetchInterval: 5000,
  });

  // Scale workers mutation
  const scaleMutation = useMutation({
    mutationFn: (targetCount: number) => apiClient.scaleWorkers(targetCount),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workers'] });
      queryClient.invalidateQueries({ queryKey: ['worker-count'] });
    },
  });

  const handleScale = (delta: number) => {
    const currentCount = countData?.count || 0;
    const newTarget = Math.max(0, Math.min(10, currentCount + delta));
    setScaleTarget(newTarget);
    scaleMutation.mutate(newTarget);
  };

  const handleScaleToTarget = () => {
    scaleMutation.mutate(scaleTarget);
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running':
        return 'bg-green-100 text-green-800';
      case 'created':
        return 'bg-blue-100 text-blue-800';
      case 'restarting':
        return 'bg-yellow-100 text-yellow-800';
      case 'exited':
      case 'missing':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  const currentCount = countData?.count || 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Shared Workers</h1>
          <p className="text-gray-600 mt-1">
            Manage shared worker containers for executing trusted functions
          </p>
        </div>
      </div>

      {/* Worker Count & Scaling */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Worker Pool</h2>
            <p className="text-sm text-gray-600 mt-1">
              Current workers: <span className="font-bold text-primary-600">{currentCount}</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handleScale(-1)}
              disabled={currentCount === 0 || scaleMutation.isPending}
              className="btn btn-secondary flex items-center"
              title="Scale down"
            >
              <Minus className="w-4 h-4" />
            </button>
            <button
              onClick={() => handleScale(1)}
              disabled={currentCount >= 10 || scaleMutation.isPending}
              className="btn btn-secondary flex items-center"
              title="Scale up"
            >
              <Plus className="w-4 h-4" />
            </button>
            <button
              onClick={() => queryClient.invalidateQueries({ queryKey: ['workers'] })}
              disabled={scaleMutation.isPending}
              className="btn btn-secondary flex items-center"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Scale to target count (max 10)
            </label>
            <input
              type="number"
              min="0"
              max="10"
              value={scaleTarget}
              onChange={(e) => setScaleTarget(parseInt(e.target.value) || 0)}
              className="input"
            />
          </div>
          <button
            onClick={handleScaleToTarget}
            disabled={scaleMutation.isPending}
            className="btn btn-primary mt-7"
          >
            {scaleMutation.isPending ? 'Scaling...' : 'Scale'}
          </button>
        </div>

        {scaleMutation.isError && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            Failed to scale workers. Please check your permissions.
          </div>
        )}

        {scaleMutation.isSuccess && (
          <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
            Workers scaled successfully!
          </div>
        )}
      </div>

      {/* Workers List */}
      <div className="card">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Workers</h2>

        {!workers || workers.length === 0 ? (
          <div className="text-center py-12">
            <Server className="w-12 h-12 text-gray-400 mx-auto mb-3" />
            <p className="text-gray-600">No workers running</p>
            <p className="text-sm text-gray-500 mt-1">
              Scale up to create workers for executing shared pool functions
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {workers.map((worker: Worker) => (
              <div
                key={worker.id}
                className="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
              >
                <div className="flex items-center gap-4">
                  <Server className="w-8 h-8 text-primary-600" />
                  <div>
                    <h3 className="font-semibold text-gray-900">{worker.container_name}</h3>
                    <p className="text-sm text-gray-600">ID: {worker.id}</p>
                  </div>
                </div>

                <div className="flex items-center gap-6">
                  <div className="text-right">
                    <p className="text-sm font-medium text-gray-700">Executions</p>
                    <p className="text-lg font-bold text-primary-600">{worker.executions}</p>
                  </div>

                  <div className="text-right">
                    <p className="text-sm font-medium text-gray-700">Status</p>
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusColor(worker.status)}`}>
                      {worker.status}
                    </span>
                  </div>

                  <div className="text-right">
                    <p className="text-sm font-medium text-gray-700">Created</p>
                    <p className="text-sm text-gray-600">
                      {new Date(worker.created_at).toLocaleString()}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Info Box */}
      <div className="card bg-blue-50 border border-blue-200">
        <h3 className="font-semibold text-blue-900 mb-2">About Shared Workers</h3>
        <ul className="text-sm text-blue-800 space-y-1">
          <li>• Functions with <code className="px-1 py-0.5 bg-blue-100 rounded">shared_pool=true</code> execute in these workers</li>
          <li>• Workers are shared across all users for efficiency</li>
          <li>• Only use for <strong>trusted, admin-created functions</strong></li>
          <li>• Functions are distributed across workers using round-robin load balancing</li>
          <li>• Workers run in separate containers from the main backend</li>
        </ul>
      </div>
    </div>
  );
}
