"""Import every model so Base.metadata is complete (Alembic, create_all)."""

from app.models.book import (
    Author,
    Book,
    BookEdition,
    ExternalCache,
    Genre,
    book_authors,
    book_genres,
)
from app.models.marketplace import (
    CachedExternalListing,
    ListingFavorite,
    ListingImage,
    ListingInquiry,
    ListingReport,
    MarketplaceListing,
    MarketplaceProvider,
)
from app.models.reading import (
    BookshelfEntry,
    Conversation,
    ConversationMessage,
    ReadingGoal,
    ReadingList,
    ReadingListItem,
    ReadingPlan,
    ReadingPlanItem,
)
from app.models.social import (
    AuditLog,
    RecommendationEvaluationRun,
    RecommendationEvent,
    Review,
    ReviewHelpfulVote,
    ReviewReport,
    SearchQuery,
    UserBookInteraction,
)
from app.models.user import EmailOTP, User, UserProfile

__all__ = [
    "Author", "Book", "BookEdition", "ExternalCache", "Genre", "book_authors", "book_genres",
    "CachedExternalListing", "ListingFavorite", "ListingImage", "ListingInquiry", "ListingReport",
    "MarketplaceListing", "MarketplaceProvider",
    "BookshelfEntry", "Conversation", "ConversationMessage", "ReadingGoal", "ReadingList",
    "ReadingListItem", "ReadingPlan", "ReadingPlanItem",
    "AuditLog", "RecommendationEvaluationRun", "RecommendationEvent", "Review", "ReviewHelpfulVote",
    "ReviewReport", "SearchQuery", "UserBookInteraction",
    "EmailOTP", "User", "UserProfile",
]
