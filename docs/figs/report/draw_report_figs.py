import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch
from matplotlib import font_manager as fm
fm.fontManager.addfont('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc')
plt.rcParams['font.family']='WenQuanYi Zen Hei'
plt.rcParams['axes.unicode_minus']=False
BLUE='#8faadc'; BLUE_L='#b4c7e7'; ORG='#fce4c4'; ORGE='#d9822b'; GR='#d9d9d9'; GRE='#7f7f7f'; DK='#222222'

def box(ax,x,y,w,h,text='',fc='white',ec=DK,lw=1.6,fs=11,bold=False,r=0.12,ls='-',tc=DK,hatch=None,va='center'):
    p=FancyBboxPatch((x,y),w,h,boxstyle=f'round,pad=0,rounding_size={r}',fc=fc,ec=ec,lw=lw,ls=ls,hatch=hatch)
    ax.add_patch(p)
    if text: ax.text(x+w/2,y+h/2,text,ha='center',va=va,fontsize=fs,fontweight='bold' if bold else 'normal',color=tc,linespacing=1.35)
    return p
def arrow(ax,x0,y0,x1,y1,style='-|>',lw=1.6,color=DK,ls='-',ms=14):
    ax.add_patch(FancyArrowPatch((x0,y0),(x1,y1),arrowstyle=style,mutation_scale=ms,lw=lw,color=color,ls=ls,shrinkA=0,shrinkB=0))


# ---------- Figure 1: SSD structure and board mapping ----------
fig,ax=plt.subplots(figsize=(7.8,4.6),dpi=260); ax.set_xlim(0,18.6); ax.set_ylim(-0.2,11.2); ax.axis('off')
box(ax,0.2,1.8,2.8,6.0,'Host\nInterface\n(NVMe)',fc='#eeeeee',fs=12,bold=True)
box(ax,3.0,8.7,6.2,2.2,'RAM Buffer = 데이터 버퍼\n128프레임 × 16KB = 2MB',fc=BLUE_L,ec='#1f4e9a',fs=10,bold=True)
box(ax,3.6,0.3,9.0,8.2,'',fc='#f6f6f6',lw=2)
ax.text(8.6,7.85,'SSD Controller',ha='center',va='center',fontsize=13,fontweight='bold')
box(ax,4.1,4.3,3.9,2.4,'Processor\n(펌웨어: FTL,\n메인 루프)',fc='white',fs=10.5)
box(ax,4.1,1.0,3.9,2.4,'Buffer\nManager',fc='white',fs=11)
box(ax,9.3,0.6,3.0,6.6,'Flash\nController\n(채널 제어)',fc=GR,fs=11.5,bold=True)
arrow(ax,6.05,8.7,6.05,6.7,style='<|-|>')
arrow(ax,6.05,4.3,6.05,3.4,style='<|-|>')
arrow(ax,3.0,4.8,4.1,4.8,style='<|-|>')
arrow(ax,8.0,5.8,9.3,5.8,style='<|-|>')
arrow(ax,8.0,2.2,9.3,2.2,style='<|-|>')
for i in range(4):
    y=6.2-i*1.8
    ax.plot([12.3,13.3],[y+0.55,y+0.55],color=DK,lw=2.2)
    for j in range(2):
        box(ax,13.3+j*2.7,y,2.5,1.1,f'Die\nCh{i}·Way{j}',fc='white',fs=9.5,r=0.08,lw=1.3)
ax.text(15.9,8.6,'NAND Flash Memory',ha='center',va='center',fontsize=12,fontweight='bold')
ax.text(15.9,-0.1,'우리 보드: 4채널 × 2way = 8 dies',ha='center',va='center',fontsize=11,color='#9c4a00',fontweight='bold')
fig.savefig('fig1_ssd.png',bbox_inches='tight',pad_inches=0.08)

# ---------- Figure 4: reorder concept ----------
fig,ax=plt.subplots(figsize=(8.4,4.7),dpi=260); ax.set_xlim(0,19.6); ax.set_ylim(0,11.0); ax.axis('off')
def cell(ax,x,y,label,kind,run=False,w=2.5,h=1.25,star=False):
    fc={'W':GR,'R':BLUE_L}[kind]; ec={'W':GRE,'R':'#1f4e9a'}[kind]
    box(ax,x,y,w,h,label,fc=fc,ec=DK if run else ec,lw=3.0 if run else 1.6,fs=11,r=0.08,hatch='//' if star else None)
x0=0.4
ax.text(0.3,10.6,'한 die의 요청 큐 (왼쪽이 맨 앞, 굵은 테두리 = 실행 중인 요청)',fontsize=10,color='#555555',va='center')
# (a)
ya=7.7
ax.text(0.3,ya+2.0,'(a) 기존 FIFO',fontsize=12,fontweight='bold',va='center')
cell(ax,x0,ya,'W1\n실행 중','W',run=True)
for i,l in enumerate(['W2','W3','W4']): cell(ax,x0+2.8*(i+1),ya,l,'W')
cell(ax,x0+2.8*4,ya,'R\n(도착)','R')
ax.text(x0+2.8*5+0.1,ya+0.62,'읽기가 선행 요청 4개를\n모두 기다린 뒤 시작\nW_die ≈ (k - ½)·T_die',fontsize=9.5,va='center',color='#9c4a00')
# (b)
yb=4.0
ax.text(0.3,yb+2.0,'(b) 제안',fontsize=12,fontweight='bold',va='center')
cell(ax,x0,yb,'W1\n실행 중','W',run=True)
cell(ax,x0+2.8,yb,'R','R')
for i,l in enumerate(['W2','W3','W4']): cell(ax,x0+2.8*(i+2),yb,l,'W')
ax.text(x0+2.8*5+0.1,yb+0.62,'읽기는 실행 중인 요청의\n남은 시간만 기다림\n평균 T_die/2, 최대 T_die',fontsize=9.5,va='center',color='#9c4a00')
ax.add_patch(FancyArrowPatch((x0+2.8*4+1.25,yb+1.45),(x0+2.8+1.25,yb+1.45),arrowstyle='-|>',mutation_scale=14,lw=1.6,color='#1f4e9a',connectionstyle='arc3,rad=0.15'))
ax.text(x0+2.8*2.75,yb+2.55,'R를 대기 쓰기 앞으로 이동',fontsize=9.5,ha='center',color='#1f4e9a')
# (c)
yc=0.4
ax.text(0.3,yc+2.0,'(c) 장벽: 같은 블록의 쓰기·지우기는 앞지르지 않음',fontsize=12,fontweight='bold',va='center')
cell(ax,x0,yc,'W1\n실행 중','W',run=True)
cell(ax,x0+2.8,yc,'W2\n(같은 블록)','W',star=True)
cell(ax,x0+2.8*2,yc,'R','R')
for i,l in enumerate(['W3','W4']): cell(ax,x0+2.8*(i+3),yc,l,'W')
ax.plot([x0+2.8*2-0.15]*2,[yc-0.1,yc+1.35],color='#c00000',lw=3)
ax.text(x0+2.8*5+0.1,yc+0.62,'장벽 앞(W2)으로는 이동하지\n않고 W3, W4만 앞지름',fontsize=9.5,va='center',color='#c00000')
fig.savefig('fig4_reorder.png',bbox_inches='tight',pad_inches=0.08)

# ---------- Figure 5: decision flow ----------
fig,ax=plt.subplots(figsize=(8.0,6.2),dpi=260); ax.set_xlim(0,18.4); ax.set_ylim(-0.9,13.6); ax.axis('off')
cx=6.3
box(ax,cx-4.2,11.8,8.4,1.2,'die가 쉬는 시점 (다음 요청 발행 직전)',fc=GR,fs=10.5,bold=True)
def dbox(y,text,h=1.7): box(ax,cx-3.9,y,7.8,h,text,fc='white',fs=10.5)
dbox(9.4,'맨 앞 요청이 처음 시작하는 요청인가?\n(READ_TRANSFER·재시도 중이 아님)')
dbox(6.9,'대기 중인 읽기 요청이 있는가?')
dbox(3.9,'가장 먼저 도착한 읽기 앞에\n같은 블록의 쓰기·지우기\n(또는 판단 불가 요청)가 있는가?',h=2.3)
box(ax,cx-3.9,1.7,7.8,1.5,'읽기를 큐의 맨 앞으로 이동\n(앞지른 읽기 수 카운터 +1)',fc=BLUE_L,ec='#1f4e9a',fs=10.5,bold=True)
box(ax,cx-4.2,-0.8,8.4,1.0,'맨 앞 요청을 우선순위 표에 올려 발행',fc=GR,fs=10.5,bold=True)
arrow(ax,cx,11.8,cx,11.1); arrow(ax,cx,9.4,cx,8.6); arrow(ax,cx,6.9,cx,6.2); arrow(ax,cx,3.9,cx,3.2); arrow(ax,cx,1.7,cx,0.2)
ax.text(cx+0.25,11.45,'',fontsize=9)
ax.text(cx+0.3,9.0,'예',fontsize=10,color='#1f4e9a'); ax.text(cx+0.3,6.5,'예',fontsize=10,color='#1f4e9a'); ax.text(cx+0.3,3.55,'아니오',fontsize=10,color='#1f4e9a')
box(ax,12.3,5.6,5.8,2.6,'재정렬하지 않음\n(기존 FIFO 순서로 발행)',fc=ORG,ec=ORGE,fs=10.5,bold=True)
ax.plot([cx+3.9,15.2],[10.25,10.25],color=DK,lw=1.6); arrow(ax,15.2,10.25,15.2,8.2)
ax.text(cx+4.1,10.5,'아니오',fontsize=10,color='#9c4a00')
arrow(ax,cx+3.9,7.75,12.3,7.1); ax.text(cx+4.1,8.0,'아니오',fontsize=10,color='#9c4a00')
arrow(ax,cx+3.9,5.05,12.3,5.95); ax.text(cx+4.1,4.4,'예 (장벽 카운터 +1)',fontsize=10,color='#9c4a00')
ax.plot([15.2,15.2],[5.6,-0.3],color=DK,lw=1.6); arrow(ax,15.2,-0.3,cx+4.2,-0.3)
ax.text(11.9,12.7,'※ 쓰기 기아 방지 한도 C는 후속 설계로,\n   첫 측정에는 적용하지 않음',fontsize=9,color='#555555',va='center')
fig.savefig('fig5_flow.png',bbox_inches='tight',pad_inches=0.08)
print('ok')
