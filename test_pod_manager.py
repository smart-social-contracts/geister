import unittest
from unittest.mock import MagicMock, patch

from pod_manager import PodManager, ORIGINAL_HOST_GPU_UNAVAILABLE


class TestPodManagerGpuFallback(unittest.TestCase):
    def test_detects_original_host_gpu_unavailable_error(self):
        error = Exception(
            "There are not enough free GPUs on the host machine to start this pod."
        )
        self.assertTrue(PodManager._is_original_host_gpu_unavailable(error))

    def test_ignores_unrelated_errors(self):
        self.assertFalse(
            PodManager._is_original_host_gpu_unavailable(
                Exception("There are no longer any instances available")
            )
        )

    def test_start_pod_falls_back_to_deploy_when_resume_fails(self):
        manager = PodManager.__new__(PodManager)
        manager.verbose = False
        manager._print = lambda *args, **kwargs: None

        with patch.object(manager, "_find_pod_by_type", return_value=("old-pod", "old-host")), \
             patch.object(manager, "get_pod_status", return_value="EXITED"), \
             patch.object(manager, "_resume_existing_pod", return_value=False), \
             patch.object(manager, "_fallback_deploy_new_pod", return_value=True) as fallback:
            success = manager.start_pod("main", deploy_new_if_needed=True)

        self.assertTrue(success)
        fallback.assert_called_once_with("main", "old-pod")

    def test_start_pod_does_not_deploy_when_resume_fails_without_flag(self):
        manager = PodManager.__new__(PodManager)
        manager.verbose = False
        manager._print = lambda *args, **kwargs: None

        with patch.object(manager, "_find_pod_by_type", return_value=("old-pod", "old-host")), \
             patch.object(manager, "get_pod_status", return_value="EXITED"), \
             patch.object(manager, "_resume_existing_pod", return_value=False), \
             patch.object(manager, "_fallback_deploy_new_pod") as fallback:
            success = manager.start_pod("main", deploy_new_if_needed=False)

        self.assertFalse(success)
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
