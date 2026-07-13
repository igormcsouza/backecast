class RepositoryAbstract:
    """Abstract base class for repository classes.

    This class defines the interface that all repository classes must implement.
    It provides a common structure for interacting with different data sources.
    """

    async def list(self) -> list[dict]:
        """List all items in the repository.

        Returns:
            list[dict]: A list of items in the repository.
        """
        raise NotImplementedError("Subclasses must implement this method.")
