<template>
  <div class="profiling-container">
    <el-row :gutter="20">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>用户价值分类分布</template>
          <div ref="pieChartRef" class="chart-box"></div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>核心品类偏好排名</template>
          <div ref="barChartRef" class="chart-box"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>各消费等级用户统计</template>
          <div ref="lineChartRef" class="chart-box-wide"></div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import axios from 'axios'

const pieChartRef = ref(null)
const barChartRef = ref(null)
const lineChartRef = ref(null)
let charts = []

// 初始化图表
const initCharts = async () => {
  // 1. 获取并渲染饼图数据
  const resDist = await axios.get('/api/stats/persona_distribution')
  const pieChart = echarts.init(pieChartRef.value)

  pieChart.setOption({
    // 1. 悬浮提示框增强：显示具体数值和百分比
    tooltip: {
      trigger: 'item',
      formatter: '{b} <br/> 数量: <b>{c}</b> ({d}%)'
    },
    // 2. 图例美化
    legend: {
      bottom: '2%',
      left: 'center',
      icon: 'circle',
      textStyle: { color: '#666' }
    },
    series: [{
      name: '用户价值分类',
      type: 'pie',
      radius: ['45%', '70%'], // 环形图设计
      avoidLabelOverlap: true,
      itemStyle: {
        borderRadius: 8,
        borderColor: '#fff',
        borderWidth: 2
      },
      // 3. 核心功能：标签引导线与多维展示
      label: {
        show: true,
        position: 'outside',
        // 格式化：显示名称 + 占比
        formatter: '{b}: {d}%',
        color: '#333'
      },
      emphasis: {
        // 4. 悬浮放大效果
        label: {
          show: true,
          fontSize: '18',
          fontWeight: 'bold',
          formatter: '{b}\n{c}人'
        },
        itemStyle: {
          shadowBlur: 10,
          shadowOffsetX: 0,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      },
      // 5. 颜色方案（对应画像的业务语义）
      data: resDist.data.data.map((item, index) => {
        const colors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c'];
        return {
          ...item,
          itemStyle: { color: colors[index % colors.length] }
        };
      })
    }]
  })

  // 2. 获取并渲染品类排名
  const resCat = await axios.get('/api/stats/category_ranking')
  const barChart = echarts.init(barChartRef.value)
  barChart.setOption({
    // 新增：配置鼠标悬浮提示框
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow' // 悬浮时显示阴影指示
      },
      formatter: '{b}: {c} 位用户' // {b}是品类名，{c}是数值
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: resCat.data.data.map(i => i.name),
      axisLabel: {
        interval: 0, // 强制显示所有标签
        rotate: 30   // 旋转30度防止名称重叠
      }
    },
    yAxis: {
      type: 'value',
      name: '用户数量'
    },
    series: [{
      name: '偏好人数',
      data: resCat.data.data.map(i => i.value),
      type: 'bar',
      itemStyle: {
        color: '#409eff',
        borderRadius: [4, 4, 0, 0] // 顶部圆角
      },
      // 新增：在柱子顶部直接显示具体数字
      label: {
        show: true,
        position: 'top',
        valueAnimation: true,
        formatter: '{c}'
      },
      barWidth: '60%'
    }]
  })

  // 3. 消费等级统计增强版
  const resCons = await axios.get('/api/stats/consumption_levels')
  const lineChart = echarts.init(lineChartRef.value)
  lineChart.setOption({
    // 1. 开启提示框，显示十字准星指示器
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
        label: { backgroundColor: '#6a7985' }
      },
      formatter: '{b} <br/> 占比人数: <b>{c}</b>'
    },
    // 2. 添加工具栏（支持下载图片、查看原始数据）
    toolbox: {
      feature: {
        dataView: { show: true, readOnly: false, title: '数据视图' },
        saveAsImage: { show: true, title: '保存图片' }
      },
      right: '5%'
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false, // 坐标轴两端不留白，折线图常用
      data: resCons.data.data.map(i => i.name)
    },
    yAxis: {
      type: 'value',
      name: '人数'
    },
    series: [{
      name: '用户数',
      data: resCons.data.data.map(i => i.value),
      type: 'line',
      smooth: true, // 平滑曲线
      symbolSize: 8, // 拐点大小
      lineStyle: {
        width: 3,
        color: '#67c23a'
      },
      // 3. 核心功能：折线点上直接显示具体数字
      label: {
        show: true,
        position: 'top',
        color: '#67c23a',
        fontWeight: 'bold'
      },
      // 4. 渐变填充区域
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(103, 194, 58, 0.5)' },
          { offset: 1, color: 'rgba(103, 194, 58, 0.1)' }
        ])
      },
      // 5. 标注最大值和最小值
      markPoint: {
        data: [
          { type: 'max', name: '最大值' },
          { type: 'min', name: '最小值' }
        ]
      }
    }]
  })

  charts = [pieChart, barChart, lineChart]
}

// 响应式缩放
const handleResize = () => charts.forEach(c => c.resize())

onMounted(() => {
  initCharts()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
.chart-box { height: 350px; width: 100%; }
.chart-box-wide { height: 300px; width: 100%; }
</style>