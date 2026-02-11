/*
 Navicat Premium Data Transfer

 Source Server         : 本机
 Source Server Type    : MySQL
 Source Server Version : 90500 (9.5.0)
 Source Host           : localhost:3306
 Source Schema         : Smart_EComm_Strategy

 Target Server Type    : MySQL
 Target Server Version : 90500 (9.5.0)
 File Encoding         : 65001

 Date: 12/02/2026 02:07:07
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for dim_item
-- ----------------------------
DROP TABLE IF EXISTS `dim_item`;
CREATE TABLE `dim_item` (
  `item_id` varchar(50) NOT NULL COMMENT '商品唯一ID',
  `category` varchar(100) DEFAULT NULL COMMENT '商品所属品类',
  `price` decimal(15,2) DEFAULT NULL COMMENT '商品单价',
  `discount_rate` decimal(5,3) DEFAULT NULL COMMENT '折扣率',
  `title_length` int DEFAULT NULL COMMENT '标题长度',
  `title_emo_score` float DEFAULT NULL COMMENT '标题情感得分',
  `img_count` int DEFAULT NULL COMMENT '图片数量',
  `has_video` tinyint(1) DEFAULT NULL COMMENT '是否有视频 (0:无, 1:有)',
  PRIMARY KEY (`item_id`),
  KEY `idx_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='商品基础属性表';

-- ----------------------------
-- Table structure for dim_user
-- ----------------------------
DROP TABLE IF EXISTS `dim_user`;
CREATE TABLE `dim_user` (
  `user_id` varchar(50) NOT NULL COMMENT '用户唯一ID',
  `age` int DEFAULT NULL COMMENT '年龄',
  `gender` tinyint DEFAULT NULL COMMENT '性别 (0:女, 1:男)',
  `user_level` int DEFAULT NULL COMMENT '用户等级',
  `register_days` int DEFAULT NULL COMMENT '注册天数',
  `total_spend` decimal(15,2) DEFAULT NULL COMMENT '历史累计消费额',
  `purchase_freq` int DEFAULT NULL COMMENT '消费频次',
  `follow_num` int DEFAULT '0' COMMENT '关注数',
  `fans_num` int DEFAULT '0' COMMENT '粉丝数',
  PRIMARY KEY (`user_id`),
  KEY `idx_user_level` (`user_level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户基础信息表';

-- ----------------------------
-- Table structure for fact_user_behavior
-- ----------------------------
DROP TABLE IF EXISTS `fact_user_behavior`;
CREATE TABLE `fact_user_behavior` (
  `behavior_id` int NOT NULL AUTO_INCREMENT,
  `user_id` varchar(50) NOT NULL,
  `item_id` varchar(50) NOT NULL,
  `pv_count` int DEFAULT '0' COMMENT '浏览量',
  `add2cart` tinyint(1) DEFAULT '0' COMMENT '是否加购',
  `collect_num` int DEFAULT '0' COMMENT '收藏次数',
  `like_num` int DEFAULT '0' COMMENT '点赞数',
  `comment_num` int DEFAULT '0' COMMENT '评论数',
  `share_num` int DEFAULT '0' COMMENT '分享数',
  `coupon_received` tinyint(1) DEFAULT '0' COMMENT '是否领券',
  `coupon_used` tinyint(1) DEFAULT '0' COMMENT '是否用券',
  `interaction_rate` float DEFAULT NULL COMMENT '交互率',
  `purchase_intent` float DEFAULT NULL COMMENT '购买意向分',
  `last_click_gap` float DEFAULT NULL COMMENT '最后一次点击间隔',
  `label` tinyint(1) DEFAULT '0' COMMENT '转化标签 (0:未购, 1:已购)',
  PRIMARY KEY (`behavior_id`),
  KEY `fk_item` (`item_id`),
  KEY `idx_user_item` (`user_id`,`item_id`),
  CONSTRAINT `fk_item` FOREIGN KEY (`item_id`) REFERENCES `dim_item` (`item_id`),
  CONSTRAINT `fk_user` FOREIGN KEY (`user_id`) REFERENCES `dim_user` (`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=300 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户行为互动事实表';

-- ----------------------------
-- Table structure for recommendation_results
-- ----------------------------
DROP TABLE IF EXISTS `recommendation_results`;
CREATE TABLE `recommendation_results` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '用户ID',
  `item_id` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '商品ID',
  `category` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '商品品类',
  `score` float DEFAULT NULL COMMENT '预测购买得分 (0-1)',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user` (`user_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2991 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ----------------------------
-- Table structure for usr_persona
-- ----------------------------
DROP TABLE IF EXISTS `usr_persona`;
CREATE TABLE `usr_persona` (
  `user_id` varchar(50) NOT NULL,
  `cluster_label` int DEFAULT NULL COMMENT 'K-means 聚类群体编号',
  `persona_tag` varchar(100) DEFAULT NULL COMMENT '画像描述 (如: 高价值极简主义者)',
  `social_influence` float DEFAULT NULL COMMENT '社交影响力得分',
  `last_update` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录画像最后更新时间，用于标签动态同步与时效性追踪',
  `consumption_level` varchar(20) DEFAULT NULL COMMENT '消费等级标签 (如: 低/中/高消费)',
  `preferred_category` varchar(50) DEFAULT NULL COMMENT '核心偏好品类 (基于互动频率最高的 category)',
  `activity_level` varchar(20) DEFAULT NULL COMMENT '活跃度标签 (如: 沉睡/活跃/忠实, 基于 pv_count)',
  `price_sensitivity` float DEFAULT NULL COMMENT '价格敏感度 (基于 discount_rate 和 purchase_freq)',
  `loyalty_score` float DEFAULT NULL COMMENT '忠诚度评分 (基于 register_days 和 purchase_intent)',
  `is_churn_risk` tinyint(1) DEFAULT '0' COMMENT '流失风险预警 (基于 last_click_gap)',
  PRIMARY KEY (`user_id`),
  CONSTRAINT `fk_persona_user` FOREIGN KEY (`user_id`) REFERENCES `dim_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户画像与标签模型表';

SET FOREIGN_KEY_CHECKS = 1;
