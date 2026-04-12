// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract SourceBountyEscrow {
    enum BountyStatus {
        None,
        Created,
        Funded,
        AnswerSubmitted,
        Accepted,
        Rejected,
        Rewarded,
        Refunded
    }

    struct Bounty {
        address creator;
        address responder;
        uint256 reward;
        bytes32 questionHash;
        bytes32 answerHash;
        bytes32 verdictDigest;
        uint64 deadline;
        bool accepted;
        BountyStatus status;
    }

    address public owner;
    address public relaySigner;
    uint256 public nextBountyId = 1;
    mapping(uint256 => Bounty) public bounties;

    event BountyCreated(uint256 indexed bountyId, address indexed creator, uint256 reward);
    event BountyFunded(uint256 indexed bountyId, uint256 reward);
    event AnswerSubmitted(uint256 indexed bountyId, address indexed responder, bytes32 answerHash);
    event VerdictRecorded(uint256 indexed bountyId, bool accepted, bytes32 verdictDigest);
    event RewardReleased(uint256 indexed bountyId, address indexed responder, uint256 reward);
    event CreatorRefunded(uint256 indexed bountyId, address indexed creator, uint256 reward);

    error NotOwner();
    error NotRelay();
    error NotCreator();
    error InvalidAddress();
    error InvalidAmount();
    error InvalidStatus();
    error InvalidDeadline();
    error TransferFailed();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyRelay() {
        if (msg.sender != relaySigner) revert NotRelay();
        _;
    }

    constructor(address owner_, address relaySigner_) {
        if (owner_ == address(0) || relaySigner_ == address(0)) revert InvalidAddress();
        owner = owner_;
        relaySigner = relaySigner_;
    }

    function setRelaySigner(address relaySigner_) external onlyOwner {
        if (relaySigner_ == address(0)) revert InvalidAddress();
        relaySigner = relaySigner_;
    }

    function createBounty(bytes32 questionHash, uint256 reward, uint64 deadline) external returns (uint256 bountyId) {
        if (questionHash == bytes32(0)) revert InvalidAmount();
        if (reward == 0) revert InvalidAmount();
        if (deadline <= block.timestamp) revert InvalidDeadline();
        bountyId = nextBountyId++;
        bounties[bountyId] = Bounty({
            creator: msg.sender,
            responder: address(0),
            reward: reward,
            questionHash: questionHash,
            answerHash: bytes32(0),
            verdictDigest: bytes32(0),
            deadline: deadline,
            accepted: false,
            status: BountyStatus.Created
        });
        emit BountyCreated(bountyId, msg.sender, reward);
    }

    function fundBounty(uint256 bountyId) external payable {
        Bounty storage bounty = _bounty(bountyId);
        if (msg.sender != bounty.creator) revert NotCreator();
        if (bounty.status != BountyStatus.Created) revert InvalidStatus();
        if (msg.value != bounty.reward) revert InvalidAmount();
        bounty.status = BountyStatus.Funded;
        emit BountyFunded(bountyId, msg.value);
    }

    function submitAnswer(uint256 bountyId, bytes32 answerHash) external {
        Bounty storage bounty = _bounty(bountyId);
        if (bounty.status != BountyStatus.Funded && bounty.status != BountyStatus.Rejected) revert InvalidStatus();
        if (answerHash == bytes32(0)) revert InvalidAmount();
        bounty.responder = msg.sender;
        bounty.answerHash = answerHash;
        bounty.status = BountyStatus.AnswerSubmitted;
        emit AnswerSubmitted(bountyId, msg.sender, answerHash);
    }

    function recordVerdict(uint256 bountyId, bool accepted, bytes32 verdictDigest) external onlyRelay {
        Bounty storage bounty = _bounty(bountyId);
        if (bounty.status != BountyStatus.AnswerSubmitted) revert InvalidStatus();
        if (verdictDigest == bytes32(0)) revert InvalidAmount();
        bounty.accepted = accepted;
        bounty.verdictDigest = verdictDigest;
        bounty.status = accepted ? BountyStatus.Accepted : BountyStatus.Rejected;
        emit VerdictRecorded(bountyId, accepted, verdictDigest);
    }

    function releaseReward(uint256 bountyId) external {
        Bounty storage bounty = _bounty(bountyId);
        if (bounty.status != BountyStatus.Accepted) revert InvalidStatus();
        bounty.status = BountyStatus.Rewarded;
        (bool ok,) = bounty.responder.call{value: bounty.reward}("");
        if (!ok) revert TransferFailed();
        emit RewardReleased(bountyId, bounty.responder, bounty.reward);
    }

    function refundCreator(uint256 bountyId) external {
        Bounty storage bounty = _bounty(bountyId);
        if (msg.sender != bounty.creator && msg.sender != owner) revert NotCreator();
        if (bounty.status != BountyStatus.Rejected && bounty.status != BountyStatus.Funded && block.timestamp <= bounty.deadline) {
            revert InvalidStatus();
        }
        if (bounty.status == BountyStatus.Rewarded || bounty.status == BountyStatus.Refunded) revert InvalidStatus();
        bounty.status = BountyStatus.Refunded;
        (bool ok,) = bounty.creator.call{value: bounty.reward}("");
        if (!ok) revert TransferFailed();
        emit CreatorRefunded(bountyId, bounty.creator, bounty.reward);
    }

    function getBounty(uint256 bountyId) external view returns (Bounty memory) {
        return _bounty(bountyId);
    }

    function _bounty(uint256 bountyId) internal view returns (Bounty storage bounty) {
        bounty = bounties[bountyId];
        if (bounty.status == BountyStatus.None) revert InvalidStatus();
    }
}
