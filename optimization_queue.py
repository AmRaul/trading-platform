"""
Optimization Queue Manager
Ensures only one optimization runs at a time, others wait in queue
"""

import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class OptimizationStatus(Enum):
    """Optimization task status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OptimizationTask:
    """Represents a single optimization task"""

    def __init__(
        self,
        task_id: str,
        config: dict,
        optimization_params: dict,
        n_trials: int,
        user_id: Optional[str] = None,
        notification_callback: Optional[Callable] = None
    ):
        self.task_id = task_id
        self.config = config
        self.optimization_params = optimization_params
        self.n_trials = n_trials
        self.user_id = user_id
        self.notification_callback = notification_callback

        self.status = OptimizationStatus.PENDING
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self.results = None
        self.error = None
        self.progress = 0

    def to_dict(self) -> Dict:
        """Convert task to dictionary"""
        return {
            'task_id': self.task_id,
            'status': self.status.value,
            'config': self.config,
            'optimization_params': self.optimization_params,
            'n_trials': self.n_trials,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'progress': self.progress,
            'results': self.results,
            'error': self.error
        }


class OptimizationQueue:
    """
    Thread-safe queue manager for optimization tasks
    Ensures only one optimization runs at a time
    """

    def __init__(self, max_parallel_optimizations: int = 1):
        """
        Initialize queue

        Args:
            max_parallel_optimizations: Maximum concurrent optimizations (default: 1)
        """
        self.max_parallel = max_parallel_optimizations
        self.queue: List[OptimizationTask] = []
        self.running_tasks: Dict[str, OptimizationTask] = {}
        self.completed_tasks: Dict[str, OptimizationTask] = {}
        self.lock = threading.Lock()
        self.worker_thread = None
        self.running = False

    def add_task(
        self,
        config: dict,
        optimization_params: dict,
        n_trials: int = 100,
        user_id: Optional[str] = None,
        notification_callback: Optional[Callable] = None
    ) -> str:
        """
        Add optimization task to queue

        Args:
            config: Base strategy configuration
            optimization_params: Parameters to optimize
            n_trials: Number of optimization trials
            user_id: User ID for notifications
            notification_callback: Callback function for notifications

        Returns:
            task_id: Unique task identifier
        """
        task_id = str(uuid.uuid4())

        task = OptimizationTask(
            task_id=task_id,
            config=config,
            optimization_params=optimization_params,
            n_trials=n_trials,
            user_id=user_id,
            notification_callback=notification_callback
        )

        with self.lock:
            self.queue.append(task)
            position = len(self.queue)

        logger.info(f"Task {task_id} added to queue (position: {position})")

        # Send notification about queue position
        if notification_callback and user_id:
            if position == 1 and len(self.running_tasks) == 0:
                message = "✅ Задача добавлена в очередь и скоро начнется"
            else:
                message = f"📥 Задача добавлена в очередь\n⏳ Позиция: {position}\n🔄 Выполняется: {len(self.running_tasks)}"

            try:
                notification_callback(user_id, message)
            except Exception as e:
                logger.error(f"Failed to send queue notification: {e}")

        # Start processing if not already running
        if not self.running:
            self.start_processing()

        return task_id

    def start_processing(self):
        """Start processing queue in background thread"""
        if self.running:
            logger.warning("Queue processing already running")
            return

        self.running = True
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()
        logger.info("Queue processing started")

    def _process_queue(self):
        """Background worker that processes queue"""
        from optimizer import OptunaOptimizer
        from database import save_optimization_result

        while self.running:
            task = None

            with self.lock:
                # Check if we can start new task
                if len(self.running_tasks) < self.max_parallel and len(self.queue) > 0:
                    task = self.queue.pop(0)
                    self.running_tasks[task.task_id] = task

            if task:
                logger.info(f"Starting optimization task {task.task_id}")
                task.status = OptimizationStatus.RUNNING
                task.started_at = datetime.now()

                try:
                    # Run optimization
                    optimizer = OptunaOptimizer(
                        base_config=task.config,
                        optimization_params=task.optimization_params,
                        n_trials=task.n_trials,
                        max_parallel_backtests=4,
                        notification_callback=task.notification_callback,
                        user_id=task.user_id
                    )

                    results = optimizer.optimize()

                    # Mark as completed
                    task.status = OptimizationStatus.COMPLETED
                    task.completed_at = datetime.now()
                    task.results = results
                    task.progress = 100

                    # Save to database
                    try:
                        # Prepare optimization data for database
                        duration = (task.completed_at - task.started_at).total_seconds() / 60
                        optimization_data = {
                            'status': 'completed',
                            'n_trials': task.n_trials,
                            'optimization_metric': results.get('optimization_metric', 'custom_score'),
                            'best_params': results.get('best_params'),
                            'best_score': results.get('best_score'),
                            'best_config': results.get('best_config'),
                            'best_results': results.get('best_results'),
                            'all_trials': results.get('all_trials', []),
                            'started_at': task.started_at,
                            'duration_minutes': duration,
                            'user_id': task.user_id
                        }
                        save_optimization_result(task.task_id, optimization_data)
                    except Exception as db_err:
                        logger.error(f"Failed to save optimization results to DB: {db_err}")

                    logger.info(f"Task {task.task_id} completed successfully")

                except Exception as e:
                    logger.error(f"Task {task.task_id} failed: {e}")
                    task.status = OptimizationStatus.FAILED
                    task.completed_at = datetime.now()
                    task.error = str(e)

                    # Send error notification
                    if task.notification_callback and task.user_id:
                        try:
                            task.notification_callback(
                                task.user_id,
                                f"❌ Оптимизация завершилась с ошибкой:\n{str(e)[:200]}"
                            )
                        except:
                            pass

                finally:
                    # Move to completed
                    with self.lock:
                        if task.task_id in self.running_tasks:
                            del self.running_tasks[task.task_id]
                        self.completed_tasks[task.task_id] = task

            else:
                # No tasks to process, sleep
                import time
                time.sleep(2)

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """
        Get task status by ID

        Args:
            task_id: Task identifier

        Returns:
            Task status dict or None if not found
        """
        with self.lock:
            # Check running
            if task_id in self.running_tasks:
                return self.running_tasks[task_id].to_dict()

            # Check completed
            if task_id in self.completed_tasks:
                return self.completed_tasks[task_id].to_dict()

            # Check queue
            for task in self.queue:
                if task.task_id == task_id:
                    return task.to_dict()

        return None

    def get_queue_status(self) -> Dict:
        """
        Get overall queue status

        Returns:
            Dict with queue statistics
        """
        with self.lock:
            return {
                'queue_length': len(self.queue),
                'running_count': len(self.running_tasks),
                'completed_count': len(self.completed_tasks),
                'queue': [task.to_dict() for task in self.queue],
                'running': [task.to_dict() for task in self.running_tasks.values()],
                'max_parallel': self.max_parallel
            }

    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel pending task

        Args:
            task_id: Task identifier

        Returns:
            True if cancelled, False if not found or already running
        """
        with self.lock:
            # Can only cancel pending tasks
            for i, task in enumerate(self.queue):
                if task.task_id == task_id:
                    task.status = OptimizationStatus.CANCELLED
                    self.queue.pop(i)
                    self.completed_tasks[task_id] = task
                    logger.info(f"Task {task_id} cancelled")
                    return True

        return False

    def stop_processing(self):
        """Stop queue processing"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        logger.info("Queue processing stopped")


# Global queue instance
global_optimization_queue = OptimizationQueue(max_parallel_optimizations=1)
